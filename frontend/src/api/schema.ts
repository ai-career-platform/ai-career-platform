/**
 * docs/api/openapi.yaml(T06 계약)에서 생성한 타입을 화면에서 쓰기 쉽게 꺼내는 도우미.
 * 생성 파일(schema.gen.ts)은 직접 고치지 말고 `npm run gen:api` 로 다시 만드세요.
 */
import type { components, operations } from './schema.gen';

export type Schemas = components['schemas'];
export type OperationId = keyof operations;

type SuccessStatus = 200 | 201 | 202 | 204;
type JsonBody<R> = R extends { content: { 'application/json': infer B } } ? B : undefined;
type Responses<O extends OperationId> = operations[O]['responses'];

/** operationId 의 성공 응답 본문 타입. 본문이 없으면(204) undefined. */
export type ResponseOf<O extends OperationId> =
  JsonBody<Responses<O>[Extract<keyof Responses<O>, SuccessStatus>]>;

/** operationId 의 JSON 요청 본문 타입. */
export type BodyOf<O extends OperationId> = JsonBody<NonNullable<operations[O]['requestBody']>>;

/** operationId 의 쿼리 파라미터. 화면 상태를 그대로 넘길 수 있게 null 도 허용합니다(전송 시 빠짐). */
export type QueryOf<O extends OperationId> = {
  [K in keyof NonNullable<operations[O]['parameters']['query']>]?:
    NonNullable<operations[O]['parameters']['query']>[K] | null;
};

/** 커서 페이지 공통 모양 (API_CONTRACT §1 페이징). */
export type Page<T> = { items: T[]; next_cursor: string | null };
