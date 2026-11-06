// Local synthetic data only; this does not implement the T17 API.
export function filterJobs(jobs, query, order='name') {
  if (!Array.isArray(jobs) || typeof query !== 'string' || !['name','category'].includes(order)) throw new TypeError('Invalid search input');
  const q=query.trim().toLocaleLowerCase('ko');
  return jobs.filter(j=>j.name.toLocaleLowerCase('ko').includes(q)).sort((a,b)=>order==='category'?a.category.localeCompare(b.category,'ko')||a.name.localeCompare(b.name,'ko'):a.name.localeCompare(b.name,'ko'));
}

export function pageJobs(items, page, size=20) {
  if (!Array.isArray(items) || !Number.isInteger(page) || page<1 || !Number.isInteger(size) || size<1) throw new RangeError('Invalid page');
  const pages=Math.max(1,Math.ceil(items.length/size));
  const current=Math.min(page,pages);
  return {items:items.slice((current-1)*size,current*size),current,pages};
}
