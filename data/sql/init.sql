-- ============================================================
-- Food Compass — Supabase 초기 스키마
-- 실행 순서: Supabase > SQL Editor > 전체 붙여넣기 후 Run
-- ============================================================


-- ============================================================
-- [1] price_snapshot
--     역할: KAMIS dailyPriceByCategoryList 응답을 그대로 적재하는 원본 스냅샷
--          (Day3 설계의 price_cache를 대체 — 별도 Fallback 캐시 불필요.
--           regday/fetched_at 자체가 신선도를 말해주므로 캐시 역할까지 흡수)
--     갱신: GitHub Actions cron이 하루 1회, 부류코드(item_category_code)별로
--          전체 품목 조회 후 UPSERT (개별 품목 코드 매핑 불필요)
--     조회: 사용자 요청 경로는 이 테이블만 item_name으로 SELECT
-- ============================================================

CREATE TABLE IF NOT EXISTS price_snapshot (
    id                  BIGSERIAL   PRIMARY KEY,
    item_category_code  TEXT        NOT NULL,  -- 부류코드 (예: "200"=채소류, 5~6개 고정값)
    item_name           TEXT        NOT NULL,  -- 품목명 (예: "배추") — 사용자 질의 매칭 기준
    item_code           TEXT        NOT NULL,  -- KAMIS 품목코드 (예: "211")
    kind_name           TEXT        NOT NULL,  -- 품종명 (예: "봄(10kg(그물망 3포기))")
    kind_code           TEXT        NOT NULL,
    rank_name           TEXT        NOT NULL,  -- 등급 (예: "상품"/"중품")
    rank_code           TEXT        NOT NULL,
    unit                TEXT        NOT NULL,
    -- dpr1=당일 dpr2=1일전 dpr3=1주일전 dpr4=2주일전 dpr5=1개월전 dpr6=1년전 dpr7=평년
    -- 콤마 포함 가격 문자열("7,286") 또는 결측치("-") 그대로 저장
    dpr1                TEXT,
    dpr2                TEXT,
    dpr3                TEXT,
    dpr4                TEXT,
    dpr5                TEXT,
    dpr6                TEXT,
    dpr7                TEXT,
    regday              DATE        NOT NULL,  -- KAMIS 조회 기준일 (p_regday)
    source              TEXT        NOT NULL DEFAULT 'KAMIS',
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (item_code, kind_code, rank_code, regday)
);

-- 사용자 질의 경로 조회 기준 (item_name으로 최신 regday 찾기)
CREATE INDEX IF NOT EXISTS idx_price_snapshot_item_name
    ON price_snapshot (item_name, regday DESC);

-- 신선도 확인 및 오래된 데이터 정리용
CREATE INDEX IF NOT EXISTS idx_price_snapshot_fetched_at
    ON price_snapshot (fetched_at DESC);


-- ============================================================
-- [2] query_log
--     역할: 사용자 질의·응답 이력 저장 (디버깅·LLMOps 활용)
--     MVP 필수 아님 — Langfuse 미도입 시 간이 대체재로 활용
--     주의: 개인정보 없음 (query 텍스트만, user_id 없음)
-- ============================================================

CREATE TABLE IF NOT EXISTS query_log (
    id          BIGSERIAL   PRIMARY KEY,
    user_query  TEXT        NOT NULL,
    route       TEXT,                           -- price / knowledge / hybrid / off-topic
    items       TEXT[],                         -- 추출된 품목 목록
    answer      TEXT,
    is_fallback BOOLEAN     NOT NULL DEFAULT FALSE,  -- 캐시 Fallback 사용 여부
    latency_ms  INTEGER,                        -- 응답 소요 시간 (ms)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_query_log_created_at
    ON query_log (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_query_log_route
    ON query_log (route);


-- ============================================================
-- [3] RLS(Row Level Security) 설정
--     백엔드 전용 서비스이므로 service_role 키로만 접근
--     anon / authenticated 역할 차단 (보안 기본값)
-- ============================================================

ALTER TABLE price_snapshot ENABLE ROW LEVEL SECURITY;
ALTER TABLE query_log      ENABLE ROW LEVEL SECURITY;

-- service_role은 RLS를 자동으로 우회하므로 별도 정책 불필요
-- 아래는 명시적 차단 (anon 키로 직접 접근 방지)
CREATE POLICY "deny_anon_price_snapshot" ON price_snapshot
    FOR ALL TO anon USING (FALSE);

CREATE POLICY "deny_anon_query_log" ON query_log
    FOR ALL TO anon USING (FALSE);

-- ============================================================
-- [4] 초기 데이터
--     실데이터는 GitHub Actions cron 적재 스크립트(추후 작성)가 채움.
--     이 스키마 파일에는 샘플 INSERT 없음 — price_snapshot 컬럼이
--     KAMIS 원본 응답 그대로라 손으로 채운 샘플이 실데이터와 어긋날 위험이 큼.
-- ============================================================