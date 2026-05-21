# AWS Policies — 데모 1주 전 보안 경화

배포 가동 후 적용할 AWS 정책 JSON 모음. 각 파일은 단독 적용 가능하며 deploy.yml 흐름과 호환되도록 검증됨.

| 파일 | 용도 | 적용 대상 |
|---|---|---|
| `ecr-lifecycle.json` | 오래된 이미지 자동 정리 | ECR repository `scifit-sync` |
| `github-oidc-trust-policy.json` | GitHub Actions → AWS OIDC 신뢰 정책 | 새 IAM role `github-actions-deploy-oidc` |
| `github-actions-deploy-policy.json` | 배포 최소 권한 (ECR + ECS + IAM PassRole + CW Logs) | 위 role의 inline/attached policy |

## 사전 조건

- AWS 콘솔 또는 CLI 사용 권한 (현재 IAM 사용자 `sungjoon`이 `Admins` 그룹 — admin 권한 보유)
- 계정: `223767250023` / 리전: `ap-northeast-2`

## 적용 순서

### 1. ECR lifecycle policy (즉시 적용 가능, 위험 0)

```bash
aws ecr put-lifecycle-policy \
  --repository-name scifit-sync \
  --region ap-northeast-2 \
  --lifecycle-policy-text file://aws/policies/ecr-lifecycle.json
```

검증:
```bash
aws ecr get-lifecycle-policy --repository-name scifit-sync --region ap-northeast-2
```

매 배포마다 sha-tagged 이미지가 ECR에 영구 누적되는 문제 해결. 비용은 미미하지만 (월 $0.6) deploy 횟수가 늘수록 image list 검색 속도 + 콘솔 UX가 떨어짐.

### 2. GitHub OIDC provider 생성 (한 번만)

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

> Thumbprint는 GitHub OIDC 인증서 SHA-1. AWS 공식 문서가 발급한 값(2023년 갱신 후 동일).

### 3. IAM role 생성 (OIDC trust + 최소 권한)

```bash
# Trust policy로 role 생성
aws iam create-role \
  --role-name github-actions-deploy-oidc \
  --assume-role-policy-document file://aws/policies/github-oidc-trust-policy.json

# Permission policy를 inline으로 부착
aws iam put-role-policy \
  --role-name github-actions-deploy-oidc \
  --policy-name deploy-min-perms \
  --policy-document file://aws/policies/github-actions-deploy-policy.json
```

### 4. deploy.yml 수정 (별도 PR)

`aws-actions/configure-aws-credentials` 호출을 access key에서 role-to-assume으로 전환:

```yaml
permissions:
  contents: read
  id-token: write   # OIDC 토큰 발급 필수

- name: Configure AWS credentials
  uses: aws-actions/configure-aws-credentials@v4
  with:
    role-to-assume: arn:aws:iam::223767250023:role/github-actions-deploy-oidc
    aws-region: ap-northeast-2
```

→ GitHub Secrets에서 `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` 제거 가능.

### 5. 기존 `github-actions-deploy` IAM user의 access key 폐기

```bash
# 액세스 키 ID 확인
aws iam list-access-keys --user-name github-actions-deploy

# 비활성화 후 삭제 (즉시 폐기 권장 — OIDC 검증 후)
aws iam update-access-key --user-name github-actions-deploy --access-key-id AKIA... --status Inactive
aws iam delete-access-key --user-name github-actions-deploy --access-key-id AKIA...
```

## Why this matters

- **현재 상태**: `github-actions-deploy` IAM 사용자가 `AdministratorAccess` 보유 + 영구 access key가 GitHub Secrets에 평문. 키 유출 시 계정 전체 권한 노출.
- **OIDC 전환 후**: 각 워크플로우 실행마다 단기(1시간) STS 토큰 발급, 영구 key 없음. role에 부착된 정책으로 권한 범위 ECR/ECS/IAM PassRole/Logs로 한정.
- **데모 1주 전** 작업으로 분류됨 — capstone staging 단계엔 위험 허용 가능하나 데모 직전엔 정리 필요.

## 본 PR의 범위

이 PR은 정책 JSON과 가이드만 추가한다. 실제 IAM 리소스 생성과 deploy.yml의 `role-to-assume` 전환은 별도 작업 (위 1~5단계). 이 분리는 두 가지 이유:

1. 정책 JSON은 코드 리뷰 대상이지만 IAM 콘솔 작업은 일회성이라 PR로 묶기 부자연스러움
2. deploy.yml 갈아끼우기는 검증된 OIDC role이 먼저 존재해야 하므로 시간 순서 분리
