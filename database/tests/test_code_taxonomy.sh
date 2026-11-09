#!/usr/bin/env bash
set -euo pipefail

# T137: disposable test database only; NEVER execute against staging.
# Loads database/tests/taxonomy/T137_code_taxonomy_mock.sql into a throwaway postgres:18.1
# container and proves the code/alias policy: code format, alias normalization and
# resolution, ambiguous terms, merge/deprecate compatibility, immutability, change log
# and privilege boundaries.
if [[ "${D1_TEST_ONLY:-}" != "YES" ]]; then
  echo "ERROR: D1_TEST_ONLY=YES is required" >&2
  exit 2
fi

container="career-t137-taxonomy-test-${GITHUB_RUN_ID:-manual}-$$"
cleanup() { docker rm -f "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$container" \
  -e POSTGRES_USER=t137test \
  -e POSTGRES_PASSWORD=t137test-disposable-only \
  -e POSTGRES_DB=t137test \
  postgres:18.1 >/dev/null

ready=0
for _ in $(seq 1 50); do
  if docker exec "$container" pg_isready -U t137test -d t137test >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
[[ "$ready" == "1" ]] || { echo "FAIL postgres never ready"; exit 1; }

psql_test() { docker exec -i "$container" psql -X -v ON_ERROR_STOP=1 -U t137test -d t137test "$@"; }
docker cp database/tests/taxonomy/T137_code_taxonomy_mock.sql "$container:/tmp/taxonomy_mock.sql"
mock_sql=/tmp/taxonomy_mock.sql

# ---- shared test body (also used by local runners that redefine psql_test/mock_sql)
psql_test -f "$mock_sql" >/dev/null
echo "PASS mock schema and sample codes loaded"

q()       { psql_test -qAtc "$1"; }
curator() { psql_test -qAtc "SET ROLE t137_curator; SELECT $1;"; }
resolve() { psql_test -qAt -F ',' -c "SET ROLE t137_reader; SELECT coalesce(input_code,'-'), coalesce(canonical_code,'-'), match_type, coalesce(is_deprecated::text,'-') FROM taxonomy_mock.resolve_term('$1', \$t\$$2\$t\$);" | tr -d '\r' | paste -sd ';' -; }
expect_eq() {
  local label="$1" got="$2" want="$3"
  [[ "$got" == "$want" ]] || { echo "FAIL $label: got '$got' want '$want'"; exit 1; }
  echo "PASS $label"
}
expect_rejected() {
  local label="$1" sql="$2"
  if psql_test -c "$sql" >/dev/null 2>&1; then
    echo "FAIL expected rejected: $label"
    exit 1
  fi
  echo "PASS expected rejected: $label"
}

# 1. resolution: code, alias, normalization, ambiguity, not found
expect_eq "code match is case-insensitive (python)"    "$(resolve skill 'python')"        "PYTHON,PYTHON,code,false"
expect_eq "Korean alias (파이썬)"                       "$(resolve skill '파이썬')"         "PYTHON,PYTHON,alias,false"
expect_eq "punctuation/space normalized (Node.js)"     "$(resolve skill ' Node . JS ')"   "NODEJS,NODEJS,code,false"
expect_eq "short alias (k8s)"                          "$(resolve skill 'K8S')"           "KUBERNETES,KUBERNETES,alias,false"
expect_eq "C++ and C# stay distinct (C++)"             "$(resolve skill 'c++')"           "CPP,CPP,alias,false"
expect_eq "C++ and C# stay distinct (C#)"              "$(resolve skill 'C#')"            "CSHARP,CSHARP,alias,false"
expect_eq "React vs React Native not confused"         "$(resolve skill 'react native')"  "REACT_NATIVE,REACT_NATIVE,code,false"
expect_eq "ambiguous term returns all candidates"      "$(resolve skill 'Spring')"        "SPRING_BOOT,SPRING_BOOT,ambiguous,false;SPRING_FRAMEWORK,SPRING_FRAMEWORK,ambiguous,false"
expect_eq "entity types are separate namespaces"       "$(resolve job_role 'python')"     "-,-,not_found,-"
expect_eq "job role alias (서버 개발자)"                "$(resolve job_role '서버 개발자')" "BACKEND_ENGINEER,BACKEND_ENGINEER,alias,false"
expect_eq "unknown term"                               "$(resolve skill 'COBOL99')"       "-,-,not_found,-"

# 2. curator changes with change log
curator "taxonomy_mock.add_code('skill', 'GOLANG', 'Go 언어(중복)', 'Golang', '1.1.0', '공고 수집 중 별도 코드로 들어온 사례')" >/dev/null
curator "taxonomy_mock.add_alias('skill', 'go lang', 'GOLANG', 'exact', '1.1.0', '표기 변형 등록')" >/dev/null
curator "taxonomy_mock.add_alias('skill', '고랭', 'GOLANG', 'exact', '1.1.0', '한글 표기 등록')" >/dev/null
expect_eq "added code resolves" "$(resolve skill 'golang')" "GOLANG,GOLANG,code,false"

# 3. rejections: format, collisions, immutability, loops, versions
expect_rejected "lowercase / hyphen code"           "SET ROLE t137_curator; SELECT taxonomy_mock.add_code('skill', 'python-3', 'x', 'Python 3', '1.1.0', '형식 위반 테스트');"
expect_rejected "duplicate code"                    "SET ROLE t137_curator; SELECT taxonomy_mock.add_code('skill', 'PYTHON', 'x', 'Python again', '1.1.0', '중복 코드 테스트');"
expect_rejected "new code equal to existing alias"  "SET ROLE t137_curator; SELECT taxonomy_mock.add_code('skill', 'K8S', 'x', 'K8s', '1.1.0', '별칭 충돌 테스트');"
expect_rejected "exact alias already used (JS)"     "SET ROLE t137_curator; SELECT taxonomy_mock.add_alias('skill', 'js', 'TYPESCRIPT', 'exact', '1.1.0', '별칭 중복 테스트');"
expect_rejected "alias equal to another code"       "SET ROLE t137_curator; SELECT taxonomy_mock.add_alias('skill', 'TypeScript', 'JAVASCRIPT', 'exact', '1.1.0', '코드 충돌 테스트');"
expect_rejected "exact + ambiguous mix"             "SET ROLE t137_curator; SELECT taxonomy_mock.add_alias('skill', 'spring', 'SPRING_BOOT', 'exact', '1.1.0', '의미 혼합 테스트');"
expect_rejected "unknown version"                   "SET ROLE t137_curator; SELECT taxonomy_mock.add_alias('skill', 'pgsql', 'POSTGRESQL', 'exact', '9.9.9', '버전 없음 테스트');"
expect_rejected "reason too short"                  "SET ROLE t137_curator; SELECT taxonomy_mock.add_alias('skill', 'pgsql', 'POSTGRESQL', 'exact', '1.1.0', 'x');"
expect_rejected "merge into itself"                 "SET ROLE t137_curator; SELECT taxonomy_mock.merge_code('skill', 'GO', 'GO', '2.0.0', '자기 자신 병합 테스트');"
expect_rejected "delete a code (owner)"             "DELETE FROM taxonomy_mock.taxonomy_codes WHERE code = 'CPP';"
expect_rejected "rename a code value (owner)"       "UPDATE taxonomy_mock.taxonomy_codes SET code = 'CPLUSPLUS' WHERE code = 'CPP';"

# 4. merge keeps old code resolvable and moves aliases
curator "taxonomy_mock.merge_code('skill', 'GOLANG', 'GO', '2.0.0', 'GO 와 같은 기술이라 병합')" >/dev/null
expect_eq "old code resolves to survivor (deprecated flag)" "$(resolve skill 'GOLANG')"  "GOLANG,GO,code,true"
expect_eq "alias moved to survivor (고랭)"                  "$(resolve skill '고랭')"     "GO,GO,alias,false"
expect_eq "alias equal to merged code dropped, still resolves" "$(resolve skill 'go lang')/$(q "SELECT count(*) FROM taxonomy_mock.taxonomy_aliases WHERE alias_norm = 'golang'")" "GOLANG,GO,code,true/0"
expect_rejected "merge into a merged code"      "SET ROLE t137_curator; SELECT taxonomy_mock.merge_code('skill', 'GO', 'GOLANG', '2.0.0', '순환 병합 테스트');"
expect_rejected "replacement loop (owner bypass)" "UPDATE taxonomy_mock.taxonomy_codes SET status = 'merged', replaced_by = 'GOLANG', deprecated_in = '2.0.0' WHERE code = 'GO';"
expect_rejected "alias onto merged code"        "SET ROLE t137_curator; SELECT taxonomy_mock.add_alias('skill', 'gopher', 'GOLANG', 'exact', '2.0.0', '병합된 코드 별칭 테스트');"
expect_rejected "reactivate merged code (owner)" "UPDATE taxonomy_mock.taxonomy_codes SET status = 'active', replaced_by = NULL, deprecated_in = NULL WHERE code = 'GOLANG';"

# 5. deprecate without replacement
curator "taxonomy_mock.deprecate_code('skill', 'SPRING_FRAMEWORK', '2.0.0', '단독 사용 빈도가 낮아 신규 입력 중단')" >/dev/null
expect_eq "deprecated code still resolves with flag" "$(resolve skill 'spring framework')" "SPRING_FRAMEWORK,SPRING_FRAMEWORK,code,true"

# 5b. deprecated -> merged is allowed; merged -> merged is not; shared ambiguous alias becomes exact
curator "taxonomy_mock.merge_code('skill', 'SPRING_FRAMEWORK', 'SPRING_BOOT', '2.0.0', '스프링 표기 단일화')" >/dev/null
expect_eq "former ambiguous alias now resolves exactly (Spring)" "$(resolve skill 'Spring')" "SPRING_BOOT,SPRING_BOOT,alias,false"
expect_eq "former ambiguous Korean alias now exact (스프링)"     "$(resolve skill '스프링')"  "SPRING_BOOT,SPRING_BOOT,alias,false"
expect_eq "merged deprecated code resolves to survivor" "$(resolve skill 'spring framework')" "SPRING_FRAMEWORK,SPRING_BOOT,code,true"
expect_eq "merge log lists aliases made exact" "$(q "SELECT jsonb_array_length(detail->'aliases_made_exact') = 2 AND detail->'aliases_made_exact' ? 'Spring' FROM taxonomy_mock.taxonomy_change_log WHERE code = 'SPRING_FRAMEWORK' AND change_type = 'merge'")" "t"
expect_rejected "re-merge an already merged code" "SET ROLE t137_curator; SELECT taxonomy_mock.merge_code('skill', 'GOLANG', 'SPRING_BOOT', '2.0.0', '다시 병합 시도 테스트');"
expect_eq "already merged code keeps its first survivor" "$(q "SELECT replaced_by || '@' || deprecated_in FROM taxonomy_mock.taxonomy_codes WHERE code = 'GOLANG'")" "GO@2.0.0"
expect_eq "T05 is_active follows status (merged/deprecated -> false)" "$(q "SELECT string_agg(code || '=' || is_active, ',' ORDER BY code) FROM taxonomy_mock.taxonomy_codes WHERE code IN ('GO','GOLANG','SPRING_FRAMEWORK')")" "GO=true,GOLANG=false,SPRING_FRAMEWORK=false"

# 6. change log is complete and append-only
expect_eq "change log rows (add, alias_add x2, merge, deprecate, merge)" "$(q "SELECT string_agg(change_type, ',' ORDER BY change_id) FROM taxonomy_mock.taxonomy_change_log")" "add,alias_add,alias_add,merge,deprecate,merge"
expect_rejected "change log UPDATE (owner)" "UPDATE taxonomy_mock.taxonomy_change_log SET reason = 'rewritten history';"
expect_rejected "change log DELETE (owner)" "DELETE FROM taxonomy_mock.taxonomy_change_log;"

# 7. privilege boundaries
expect_rejected "reader add_alias()"        "SET ROLE t137_reader; SELECT taxonomy_mock.add_alias('skill', 'pgsql', 'POSTGRESQL', 'exact', '1.1.0', '권한 테스트입니다');"
expect_rejected "reader INSERT code"        "SET ROLE t137_reader; INSERT INTO taxonomy_mock.taxonomy_codes (entity_type, code, name_ko, name_en, introduced_in) VALUES ('skill','RUST','러스트','Rust','1.1.0');"
expect_rejected "reader read change log"    "SET ROLE t137_reader; SELECT count(*) FROM taxonomy_mock.taxonomy_change_log;"
expect_rejected "curator UPDATE directly"   "SET ROLE t137_curator; UPDATE taxonomy_mock.taxonomy_codes SET name_en = 'X' WHERE code = 'GO';"
expect_rejected "curator DELETE alias directly" "SET ROLE t137_curator; DELETE FROM taxonomy_mock.taxonomy_aliases;"

# 8. consistency report
expect_eq "validate_taxonomy() reports no violations" "$(psql_test -qAtc "SET ROLE t137_curator; SELECT count(*) FROM taxonomy_mock.validate_taxonomy();")" "0"

echo "T137_CODE_TAXONOMY_TEST=PASS"
