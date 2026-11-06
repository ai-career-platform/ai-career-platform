// Synthetic data only. Data definitions and T67 API are not yet approved.
export function filterSeries(points, role, start, end) {
  if (!Array.isArray(points) || typeof role !== 'string' || typeof start !== 'string' || typeof end !== 'string') throw new TypeError('조회 조건을 확인하세요.');
  if (start && end && start>end) throw new RangeError('시작 기간은 종료 기간보다 늦을 수 없습니다.');
  return points.filter(p=>(!role||p.role===role)&&(!start||p.period>=start)&&(!end||p.period<=end)).sort((a,b)=>a.period.localeCompare(b.period));
}
