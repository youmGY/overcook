"""
Hand Gesture Recognition — 60-dim (정규화 좌표 56 + 엄지 각도 코사인 4)
augmentation 없이 학습.

엄지 각도 코사인 4개:
  1. cos(∠ 1-0-5) : 엄지-검지 벌림 (wrist 기준)
  2. cos(∠ 0-1-2) : CMC 굽힘
  3. cos(∠ 1-2-3) : MCP 굽힘
  4. cos(∠ 2-3-4) : IP 굽힘

사용법:
    python train/train_60f_norm_thumb.py
    (train/landmarks.npz 필요)
"""

# ============================================================
# 임포트
# ============================================================
import os
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import TensorDataset, DataLoader
from sklearn.model_selection import train_test_split

# ============================================================
# 설정
# ============================================================
HAGRID_LABELS = [
    'call', 'dislike', 'fist', 'four', 'like', 'mute', 'no_gesture',
    'ok', 'one', 'palm', 'peace', 'peace_inverted', 'rock',
    'stop', 'stop_inverted', 'three', 'three2', 'two_up', 'two_up_inverted',
]

GAME_LABELS = ['finger_1', 'finger_2', 'finger_3', 'finger_4', 'finger_5', 'thumbs_up', 'fist']
NUM_CLASSES = len(GAME_LABELS)

LABEL_REMAP = {
    8:  0,   # one → finger_1
    10: 1,   # peace → finger_2
    11: 1,   # peace_inverted → finger_2
    17: 1,   # two_up → finger_2
    18: 1,   # two_up_inverted → finger_2
    16: 2,   # three2 → finger_3
    3:  3,   # four → finger_4
    9:  4,   # palm → finger_5
    13: 4,   # stop → finger_5
    14: 4,   # stop_inverted → finger_5
    4:  5,   # like → thumbs_up
    2:  6,   # fist → fist
    1:  5,   # dislike → thumbs_up
}

HIDDEN = (64, 32)
INPUT_DIM = 60  # 56 (norm coords) + 4 (thumb angle cosines)
WEBCAM_REPEAT_F2 = 8  # finger_2 웹캠 데이터 오버샘플링 배수
WEBCAM_REPEAT_F3 = 1  # finger_3 웹캠 데이터 오버샘플링 배수
WEBCAM_REPEAT_F5 = 6  # finger_5 웹캠 데이터 오버샘플링 배수

print(f"특성 차원: {INPUT_DIM}, 히든 레이어: {HIDDEN}")

# ============================================================
# 좌표 정규화 함수
# ============================================================

def normalize_landmarks(lm: np.ndarray, is_left: bool) -> np.ndarray:
    """(21, 3) 랜드마크 → 정규화된 (21, 3) 좌표. 실패 시 None 반환."""
    lm = lm - lm[0]

    v1 = lm[17].copy()
    v2 = lm[5].copy()

    norm_v1 = np.linalg.norm(v1)
    if norm_v1 < 1e-8:
        return None

    ex = v1 / norm_v1

    v2_perp = v2 - np.dot(v2, ex) * ex
    norm_v2_perp = np.linalg.norm(v2_perp)
    if norm_v2_perp < 1e-8:
        return None

    ey = v2_perp / norm_v2_perp
    ez = np.cross(ex, ey)

    R = np.stack([ex, ey, ez], axis=0)
    lm = (R @ lm.T).T

    lm = lm / norm_v1

    if is_left:
        lm[:, 2] = -lm[:, 2]

    return lm.astype(np.float32)


def _cos_angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """세 점 a-b-c 에서 꼭짓점 b 의 각도 코사인을 구한다."""
    v1 = a - b
    v2 = c - b
    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)
    if n1 < 1e-8 or n2 < 1e-8:
        return 0.0
    return float(np.dot(v1, v2) / (n1 * n2))


def landmarks_to_features(lm_norm: np.ndarray) -> np.ndarray:
    """정규화된 (21, 3) → 60차원 피처 벡터.
    56차원 좌표 + 엄지 각도 코사인 4개.
    """
    # --- 56-dim 정규화 좌표 ---
    feats = []
    for i in range(21):
        if i == 0:
            continue
        if i == 17:
            continue
        if i == 5:
            feats.append(lm_norm[i, 0])
            feats.append(lm_norm[i, 1])
        else:
            feats.extend(lm_norm[i].tolist())

    # --- 4 엄지 각도 코사인 ---
    # 1) 엄지-검지 벌림: ∠ joint1 - joint0 - joint5
    feats.append(_cos_angle(lm_norm[1], lm_norm[0], lm_norm[5]))
    # 2) CMC 굽힘: ∠ joint0 - joint1 - joint2
    feats.append(_cos_angle(lm_norm[0], lm_norm[1], lm_norm[2]))
    # 3) MCP 굽힘: ∠ joint1 - joint2 - joint3
    feats.append(_cos_angle(lm_norm[1], lm_norm[2], lm_norm[3]))
    # 4) IP 굽힘: ∠ joint2 - joint3 - joint4
    feats.append(_cos_angle(lm_norm[2], lm_norm[3], lm_norm[4]))

    return np.array(feats, dtype=np.float32)


# ============================================================
# landmarks.npz 로드 & 정규화
# ============================================================
npz_path = os.path.join(os.path.dirname(__file__), 'landmarks.npz')
if not os.path.exists(npz_path):
    print(f"[ERROR] {npz_path} 파일이 없습니다.")
    raise SystemExit(1)

data = np.load(npz_path)
landmarks_all = data['landmarks']
labels_raw = data['labels']
handedness = data['handedness']

print(f"HaGRID 로드: {landmarks_all.shape[0]} 샘플")

# 웹캠 데이터 로드 & 합치기
base_dir = os.path.dirname(__file__)
webcam_groups = {
    'finger_2': (['landmarks_finger2.npz'], WEBCAM_REPEAT_F2),
    'finger_3': (['landmarks_finger3.npz', 'landmarks_finger3_sy.npz'], WEBCAM_REPEAT_F3),
    'finger_5': (['landmarks_finger5.npz'], WEBCAM_REPEAT_F5),
}

for group_name, (files, repeat) in webcam_groups.items():
    group_count = 0
    for wf in files:
        wf_path = os.path.join(base_dir, wf)
        if os.path.exists(wf_path):
            wd = np.load(wf_path)
            wl = wd['landmarks']
            wlab = wd['labels']
            wh = wd['handedness']
            wl_rep = np.repeat(wl, repeat, axis=0)
            wlab_rep = np.repeat(wlab, repeat, axis=0)
            wh_rep = np.repeat(wh, repeat, axis=0)
            landmarks_all = np.concatenate([landmarks_all, wl_rep])
            labels_raw = np.concatenate([labels_raw, wlab_rep])
            handedness = np.concatenate([handedness, wh_rep])
            group_count += len(wl)
            print(f"  {wf}: {len(wl)}개 × {repeat} = {len(wl_rep)}개 추가")
    if group_count > 0:
        print(f"  {group_name} 합계: {group_count}개 (×{repeat} = {group_count * repeat}개)")
print(f"전체: {landmarks_all.shape[0]} 샘플")

X_list = []
y_list = []
skipped = 0

for i in range(len(landmarks_all)):
    hagrid_label = int(labels_raw[i])
    if hagrid_label not in LABEL_REMAP:
        skipped += 1
        continue

    game_label = LABEL_REMAP[hagrid_label]
    is_left = (handedness[i] == 0)

    lm_norm = normalize_landmarks(landmarks_all[i], is_left)
    if lm_norm is None:
        skipped += 1
        continue

    X_list.append(landmarks_to_features(lm_norm))
    y_list.append(game_label)

X = np.array(X_list)
y = np.array(y_list)

print(f"\n정규화 완료: {X.shape[0]} 샘플 (제외: {skipped})")
print(f"특성 shape: {X.shape}")
for lbl, name in enumerate(GAME_LABELS):
    print(f"  {name}: {(y == lbl).sum()}개")

# 언더샘플링
min_count = min((y == lbl).sum() for lbl in range(NUM_CLASSES))
print(f"\n언더샘플링: 클래스당 {min_count}개")
rng = np.random.RandomState(42)
keep_idx = []
for lbl in range(NUM_CLASSES):
    idx = np.where(y == lbl)[0]
    keep_idx.append(rng.choice(idx, size=min_count, replace=False))
keep_idx = np.concatenate(keep_idx)
rng.shuffle(keep_idx)
X = X[keep_idx]
y = y[keep_idx]

print(f"언더샘플링 후: {X.shape[0]} 샘플")

# ============================================================
# Train/Val 분할 & DataLoader
# ============================================================
X_train, X_val, y_train, y_val = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

train_dataset = TensorDataset(torch.FloatTensor(X_train), torch.LongTensor(y_train))
val_dataset = TensorDataset(torch.FloatTensor(X_val), torch.LongTensor(y_val))

train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True)
val_loader = DataLoader(val_dataset, batch_size=64, shuffle=False)

print(f"Train: {len(X_train)}, Val: {len(X_val)}")

# ============================================================
# MLP 모델 정의
# ============================================================
class GestureMLP(nn.Module):
    def __init__(self, input_dim=INPUT_DIM, num_classes=NUM_CLASSES, hidden=(128, 64)):
        super().__init__()
        layers = []
        prev = input_dim
        for h in hidden:
            layers.append(nn.Linear(prev, h))
            layers.append(nn.ReLU())
            prev = h
        layers.append(nn.Linear(prev, num_classes))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x)

# ============================================================
# 학습 (Early Stopping)
# ============================================================
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f"Device: {device}")

model = GestureMLP(hidden=HIDDEN).to(device)
criterion = nn.CrossEntropyLoss()
optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

PATIENCE = 10
best_val_loss = float('inf')
patience_counter = 0
best_state = None
NUM_EPOCHS = 200

for epoch in range(NUM_EPOCHS):
    model.train()
    train_loss = 0.0
    for X_batch, y_batch in train_loader:
        X_batch, y_batch = X_batch.to(device), y_batch.to(device)
        optimizer.zero_grad()
        out = model(X_batch)
        loss = criterion(out, y_batch)
        loss.backward()
        optimizer.step()
        train_loss += loss.item() * len(X_batch)
    train_loss /= len(train_loader.dataset)

    model.eval()
    val_loss = 0.0
    correct = 0
    with torch.no_grad():
        for X_batch, y_batch in val_loader:
            X_batch, y_batch = X_batch.to(device), y_batch.to(device)
            out = model(X_batch)
            loss = criterion(out, y_batch)
            val_loss += loss.item() * len(X_batch)
            correct += (out.argmax(1) == y_batch).sum().item()
    val_loss /= len(val_loader.dataset)
    val_acc = correct / len(val_loader.dataset)

    if (epoch + 1) % 10 == 0 or epoch == 0:
        print(f"Epoch {epoch+1:3d} | Train Loss: {train_loss:.4f} | Val Loss: {val_loss:.4f} | Val Acc: {val_acc:.4f}")

    if val_loss < best_val_loss:
        best_val_loss = val_loss
        best_state = {k: v.clone() for k, v in model.state_dict().items()}
        patience_counter = 0
    else:
        patience_counter += 1
        if patience_counter >= PATIENCE:
            print(f"\n★ Early Stopping at epoch {epoch+1} (best val_loss: {best_val_loss:.4f})")
            break

model.load_state_dict(best_state)

# ============================================================
# 최종 정확도 평가
# ============================================================
model.eval()
correct = 0
total = 0
with torch.no_grad():
    for X_batch, y_batch in val_loader:
        X_batch, y_batch = X_batch.to(device), y_batch.to(device)
        out = model(X_batch)
        correct += (out.argmax(1) == y_batch).sum().item()
        total += len(y_batch)

print(f"\n최종 정확도: {correct / total:.4f} ({correct}/{total})")

# ============================================================
# ONNX 변환 & 저장
# ============================================================
import onnx

model.eval()
model.cpu()

dummy_input = torch.randn(1, INPUT_DIM)
onnx_dir = os.path.dirname(__file__)
tmp_path = os.path.join(onnx_dir, 'gesture_mlp_60f_tmp.onnx')
onnx_path = os.path.join(onnx_dir, 'gesture_mlp_60f.onnx')

torch.onnx.export(
    model,
    dummy_input,
    tmp_path,
    input_names=['input'],
    output_names=['output'],
    dynamic_axes={
        'input': {0: 'batch_size'},
        'output': {0: 'batch_size'},
    },
    opset_version=11,
)

onnx_model = onnx.load(tmp_path)
onnx.save_model(onnx_model, onnx_path, save_as_external_data=False)
os.remove(tmp_path)
if os.path.exists(tmp_path + '.data'):
    os.remove(tmp_path + '.data')

print(f"\nONNX 모델 저장 완료: {onnx_path}")
print(f"파일 크기: {os.path.getsize(onnx_path) / 1024:.1f} KB")
print(f"입력: {INPUT_DIM}차원 (정규화 좌표 56 + 엄지 각도 코사인 4)")
print(f"출력: {NUM_CLASSES}클래스 {GAME_LABELS}")
