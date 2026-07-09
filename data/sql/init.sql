-- ============================================================
-- Food Compass — Supabase 초기 스키마
-- 실행 순서: Supabase > SQL Editor > 전체 붙여넣기 후 Run
-- ============================================================


-- ============================================================
-- [1] price_cache
--     역할: KAMIS API 장애 시 Fallback으로 사용하는 가격 캐시
--     갱신: get_raw_price 호출 성공 시마다 UPSERT
--     조회: API 실패 시 SELECT + is_fallback=True 플래그 반환
-- ============================================================

CREATE TABLE IF NOT EXISTS price_cache (
    item_name   TEXT        PRIMARY KEY,
    source      TEXT        NOT NULL DEFAULT 'KAMIS',
    price_data  JSONB       NOT NULL,
    cached_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- price_data JSONB 구조 (RawPriceOutput 스키마와 1:1 대응)
-- {
--   "dpr1": "4,500",   -- 당일가 (원, 콤마 포함 문자열 · "-" = 결측)
--   "dpr5": "4,200",   -- 전월가 (원)
--   "dpr7": "2,800",   -- 평년가 (원, judge_price 기준가)
--   "unit": "100g"     -- 판매 단위 (예: "1kg", "1개", "100g")
-- }

-- 오래된 캐시 조회 시 활용 (cached_at 기준 정렬)
CREATE INDEX IF NOT EXISTS idx_price_cache_cached_at
    ON price_cache (cached_at DESC);


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

ALTER TABLE price_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE query_log   ENABLE ROW LEVEL SECURITY;

-- service_role은 RLS를 자동으로 우회하므로 별도 정책 불필요
-- 아래는 명시적 차단 (anon 키로 직접 접근 방지)
CREATE POLICY "deny_anon_price_cache" ON price_cache
    FOR ALL TO anon USING (FALSE);

CREATE POLICY "deny_anon_query_log" ON query_log
    FOR ALL TO anon USING (FALSE);


-- ============================================================
-- [4] 초기 데이터 (선택 — 테스트용 샘플 5개)
--     Day2 Mock 픽스처와 동일한 품목으로 구성
-- ============================================================

INSERT INTO price_cache (item_name, source, price_data, cached_at)
VALUES
    ('상추', 'KAMIS', '{"dpr1":"4500","dpr5":"3800","dpr7":"2800","unit":"100g"}',  NOW()),
    ('배추', 'KAMIS', '{"dpr1":"2100","dpr5":"2000","dpr7":"2300","unit":"1포기"}', NOW()),
    ('오이', 'KAMIS', '{"dpr1":"1200","dpr5":"1100","dpr7":"1400","unit":"1개"}',   NOW()),
    ('당근', 'KAMIS', '{"dpr1":"2800","dpr5":"2600","dpr7":"3100","unit":"1개"}',   NOW()),
    ('깻잎', 'KAMIS', '{"dpr1":"-",   "dpr5":"1500","dpr7":"1300","unit":"100g"}',  NOW())
ON CONFLICT (item_name) DO NOTHING;
