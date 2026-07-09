bash'''
pip install chromadb

# GCP Cloud Run과 영구 저장소를 사용한 ChromaDB 서비스 배포

ChromaDB를 Google Cloud Run에 배포하는 가이드에 오신 것을 환영합니다.
이 문서는 Google Cloud Platform, 즉 GCP에서 Cloud Run을 사용해 ChromaDB 서비스를 배포하고, Google Cloud Storage, 즉 GCS 버킷을 영구 저장소로 연결하는 방법을 안내합니다.

이 설정을 통해 ChromaDB 서비스를 안전하게 운영할 수 있으며, GCP의 안정적인 인프라를 기반으로 데이터를 유지할 수 있습니다.

---

## 사전 준비 사항

진행하기 전에 다음 항목들이 준비되어 있어야 합니다.

* Google Cloud 계정
* Google Cloud 계정으로 인증된 `gcloud CLI`
* 설정이 완료된 Google Cloud 프로젝트

GCP나 `gcloud CLI`를 처음 사용하는 경우, Google에서 제공하는 공식 문서를 참고해 시작할 수 있습니다.

주의: 이 배포 방식은 Cloud Run의 CSI 볼륨 기능을 사용하므로, 최신 버전의 `gcloud CLI`가 설치되어 있어야 합니다.
다음 명령어로 `gcloud CLI`를 업데이트할 수 있습니다.

```bash
gcloud components update
```

또한 셸 스크립트를 사용하므로, Windows 환경에서 Unix 계열 셸이 없다면 Git Bash를 사용하는 것을 권장합니다.

아래 단계에서 설명하는 설정값을 수정하기 위해, 먼저 이 프로젝트를 본인의 환경에 클론하세요.

---

## 배포를 위한 정보 준비

다음 파라미터들은 Cloud Run에 ChromaDB 서비스를 배포할 때 설정을 맞춤화하는 데 사용됩니다.
아래 배포 단계를 진행하기 전에 해당 값들을 미리 확인하고 준비하세요.

| 파라미터                 | 설명                                                                                                                                                  |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `<YOUR_BUCKET_NAME>` | ChromaDB 데이터가 저장될 Google Cloud Storage 버킷 이름입니다. 이 버킷은 다음 단계에서 생성됩니다.                                                                               |
| `<REGION>`           | Google Cloud Storage 버킷과 Cloud Run 서비스가 배포될 리전입니다. 사용자 위치와 요구사항에 따라 선택합니다. 예: EU 서부 지역은 `europe-west1`, 미국 중부 지역은 `us-central1`                     |
| `<YOUR_PROJECT_ID>`  | Google Cloud 프로젝트 ID입니다. Google Cloud Console의 프로젝트 이름 아래나 프로젝트 설정 페이지에서 확인할 수 있습니다.                                                                |
| `<SERVICE_NAME>`     | Cloud Run 서비스의 이름입니다. 예: `chroma`                                                                                                                   |
| `<SERVICE_ACCOUNT>`  | 서비스를 실행할 GCP 서비스 계정입니다. 보통 기본 Compute Engine 서비스 계정을 사용하며, 이는 Google Cloud 프로젝트의 IAM 페이지에서 확인할 수 있습니다. 다만 보안상으로는 이 서비스 전용 서비스 계정을 새로 만드는 것이 더 좋습니다. |
| `<API_TOKEN>`        | 인증에 사용할 API 토큰입니다. 이 토큰은 ChromaDB 서비스에 요청을 보낼 때 인증용으로 사용됩니다. 저장소에서 제공하는 `generate_token.sh` 스크립트를 사용해 토큰을 생성할 수 있습니다.                               |

---

## Step 1: Google Cloud Storage 버킷 생성

먼저 ChromaDB 데이터를 영구적으로 저장할 전용 GCS 버킷을 생성합니다.
`<YOUR_BUCKET_NAME>`에는 원하는 버킷 이름을, `<REGION>`에는 리전 이름을, `<YOUR_PROJECT_ID>`에는 Google Cloud 프로젝트 ID를 넣어 실행합니다.

```bash
gsutil mb -p <YOUR_PROJECT_ID> -l <REGION> gs://<YOUR_BUCKET_NAME>/
```

`<REGION>`에는 원하는 버킷 리전을 입력합니다.
예를 들어 EU 서부 지역은 `europe-west1`, 미국 중부 지역은 `us-central1`을 사용할 수 있습니다.

이 버킷은 ChromaDB 데이터를 저장하는 데 사용됩니다. 따라서 Cloud Run 서비스가 스케일 다운되거나 재시작되더라도 데이터가 유지됩니다.

---

## Step 2: 사용자 지정 Cloud Run YAML 파일 생성

`generate_yaml.sh` 스크립트는 사용자의 버킷 이름과 프로젝트 ID에 맞는 Cloud Run YAML 파일을 생성하기 위해 제공됩니다.

이 bash 스크립트를 수정하여 다음 변수들을 바꿔야 합니다.

* `SERVICE_NAME`: Cloud Run 서비스 이름입니다. 기본값은 `chroma`입니다.
* `SERVICE_ACCOUNT`: 서비스를 실행할 GCP 서비스 계정입니다. 보통 기본 Compute Engine 서비스 계정을 사용하며, Google Cloud 프로젝트 IAM 페이지에서 이름을 확인할 수 있습니다.
* `SERVICE_REGION`: 서비스가 배포될 리전 이름입니다. 예: `europe-west1`
* `API_TOKEN`: 원하는 방식으로 생성한 영문자와 숫자로 이루어진 문자열입니다. 원치 않는 접근을 막기 위해 예시 값을 반드시 다른 값으로 변경해야 합니다. `generate_token.sh` 스크립트를 사용하면 API 토큰을 쉽게 생성할 수 있습니다.
* `BUCKET_NAME`: Step 1에서 생성한 버킷 이름입니다.
* `project_id`: Google Cloud 프로젝트 ID입니다.

원본 `generate_yaml.sh` 파일을 직접 수정하기보다는, 다음처럼 복사본을 만들어 수정하는 것을 권장합니다.

```bash
cp generate_yaml.sh test_generate_yaml.sh
```

참고: `test_`로 시작하는 파일들은 Git에서 무시되도록 설정되어 있습니다.

---

## Step 3: Cloud Run 서비스 배포

다음 `gcloud` 명령어를 실행하여 서비스를 배포합니다.

```bash
gcloud run services replace deploy.yaml --project <YOUR_PROJECT_ID>
```

참고: Step 2 명령어 실행 결과로 출력되는 두 번째 명령어를 복사해서 사용할 수도 있습니다.

---

## 알려진 이슈

## Step 4: 서비스에 인증되지 않은 트래픽 허용

다음 `gcloud` 명령어를 실행하여 서비스에 인증되지 않은 트래픽을 허용합니다.

```bash
gcloud run services add-iam-policy-binding <SERVICE_NAME> --member="allUsers" --role="roles/run.invoker" --region=<REGION> --project=<YOUR_PROJECT_ID>
```

참고: Step 2 명령어 실행 결과로 출력되는 두 번째 명령어를 복사해서 사용할 수도 있습니다.

주의: 이 설정은 YAML 파일에서 지정할 수 없습니다.

---

## Step 5: Chroma가 정상적으로 실행되는지 확인

ChromaDB 서비스 URL을 가져온 뒤, `/api/v1/heartbeat` 엔드포인트로 GET 요청을 보내 정상 실행 여부를 확인합니다.

`<YOUR_SERVICE_URL>`에는 배포된 Cloud Run 서비스 URL을 넣습니다.
이 URL은 이전 명령어의 출력 결과에서 확인하거나, Google Cloud Console의 Cloud Run 서비스 상세 페이지에서 확인할 수 있습니다.

```bash
curl https://chroma-mnnxrvri3q-du.a.run.app/api/v1/heartbeat
```

정상적으로 실행 중이라면 다음과 비슷한 응답을 받게 됩니다.

```json
{"nanosecond heartbeat":1724920144119441795}
```

이 응답은 ChromaDB 서비스가 정상적으로 실행되고 있음을 의미합니다.

---

## Step 6: ChromaDB 서비스 테스트

이제 Chroma 공식 문서를 참고하여 ChromaDB 서비스를 테스트할 수 있습니다.

Python 클라이언트, REST API 또는 지원되는 다른 클라이언트를 사용하여 ChromaDB 서비스와 상호작용할 수 있습니다.
클라이언트를 설정할 때는 올바른 API 토큰과 서비스 URL을 사용해야 합니다.

---

## Chroma Python Client 사용하기

다음 명령어로 Chroma Python 클라이언트 라이브러리를 설치합니다.

```bash
pip install chromadb
```

그 다음, 아래 코드를 사용하여 ChromaDB 서비스와 상호작용할 수 있습니다.

`<YOUR_SERVICE_URL>`과 `<YOUR_API_TOKEN>`을 배포된 Cloud Run 서비스 URL과 API 토큰으로 바꿔야 합니다.
API 토큰은 `deploy.yaml` 파일이나 Google Cloud Console의 Cloud Run 서비스 상세 정보에서 확인할 수 있습니다.

```python
import chromadb
from chromadb.config import Settings

# 서비스 URL과 API 토큰을 사용하여 Chroma 클라이언트 생성
client = chromadb.HttpClient(
    host="<YOUR_SERVICE_URL>",
    port=443,
    ssl=True,
    settings=Settings(
        chroma_client_auth_provider="chromadb.auth.token_authn.TokenAuthClientProvider",
        chroma_client_auth_credentials="abcdefghijklmnopqrstuvwxyz",
        anonymized_telemetry=False
    )
)
```

이제 `client` 객체를 사용하여 ChromaDB 서비스와 상호작용할 수 있습니다.
예를 들어 컬렉션을 생성하거나, 문서를 추가하거나, 문서를 조회하는 작업을 수행할 수 있습니다.

Python 클라이언트 라이브러리를 사용하는 더 자세한 방법은 Chroma 공식 문서를 참고하세요.

---

## 성능 테스트

ChromaDB 배포 성능을 테스트하기 위한 스크립트가 `jobs/load-test` 폴더에 제공됩니다.

사용 방법은 다음과 같습니다.

먼저 `.env.example` 파일을 `.env` 파일로 복사한 뒤, 필요한 변수들을 입력합니다.

필요하다면 가상환경을 생성하고, `requirements.txt`에 나열된 모듈들을 설치합니다.

그 다음 아래 명령어를 실행합니다.

```bash
python load-test.py
```
