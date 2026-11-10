import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent, PointerEvent } from 'react';
import type { MarketPeriod, MarketPoint, MarketUnit } from '../api/marketTrends';
import {
  bucketsBetween, chartSegments, formatAxisValue, formatMetricValue, niceMax, periodLabel,
} from '../pages/marketTrendFormat';
import './MarketTrendChart.css';

type MarketTrendChartProps = {
  /** 그래프 제목 (스크린리더 이름에도 씀) */
  title: string;
  observations: MarketPoint[];
  period: MarketPeriod;
  from: string;
  to: string;
  unit: MarketUnit;
};

const HEIGHT = 260;
const MARGIN = { top: 16, right: 20, bottom: 36, left: 60 };
/** 점이 이보다 많으면 선만 그리고, 떨어진 한 점짜리 구간만 표시합니다. */
const DENSE_POINTS = 60;
const FALLBACK_WIDTH = 720;

/** 컨테이너 폭을 따라 다시 그립니다(ResizeObserver 가 없으면 기본 폭). */
function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(FALLBACK_WIDTH);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => {
      const next = Math.round(entry?.contentRect.width ?? 0);
      if (next > 0) setWidth(next);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

const shortLabel = (date: string, period: MarketPeriod, withYear: boolean) =>
  period === 'month' ? `${date.slice(0, 4)}.${date.slice(5, 7)}` : withYear ? date.replaceAll('-', '.') : date.slice(5).replace('-', '.');

/**
 * 채용시장 지표 시계열 선 그래프 (단일 계열). 값은 API 관측값 그대로이고,
 * 관측이 없는 구간은 선을 끊어 빈 구간으로 둡니다(0으로 채우지 않음).
 * 포인터·키보드(좌우 화살표, Home/End)로 구간별 값을 확인합니다. 같은 값은 표로도 제공합니다.
 */
export function MarketTrendChart({ title, observations, period, from, to, unit }: MarketTrendChartProps) {
  const [containerRef, width] = useWidth();
  const [active, setActive] = useState<number | null>(null);

  const buckets = bucketsBetween(from, to, period);
  const segments = chartSegments(observations, buckets, period);
  const placed = segments.flat();
  const plotWidth = Math.max(width - MARGIN.left - MARGIN.right, 40);
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const yMax = niceMax(Math.max(0, ...placed.map((p) => p.value)), unit);
  const x = (index: number) => MARGIN.left + (buckets.length <= 1 ? plotWidth / 2 : (index * plotWidth) / (buckets.length - 1));
  const y = (value: number) => MARGIN.top + plotHeight * (1 - value / yMax);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => t * yMax);
  const labelCount = Math.max(2, Math.min(buckets.length, Math.floor(plotWidth / 84)));
  const labelIndexes = buckets.length <= 1 ? [0]
    : [...new Set(Array.from({ length: labelCount }, (_, i) => Math.round((i * (buckets.length - 1)) / (labelCount - 1))))];
  const dense = placed.length > DENSE_POINTS;
  const current = active !== null ? placed[active] : undefined;

  const move = (next: number) => setActive(Math.min(Math.max(next, 0), placed.length - 1));
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (placed.length === 0) return;
    const keys: Record<string, () => void> = {
      ArrowRight: () => move(active === null ? 0 : active + 1),
      ArrowLeft: () => move(active === null ? placed.length - 1 : active - 1),
      Home: () => move(0),
      End: () => move(placed.length - 1),
      Escape: () => setActive(null),
    };
    const action = keys[event.key];
    if (!action) return;
    event.preventDefault();
    action();
  };
  const onPointerMove = (event: PointerEvent<SVGRectElement>) => {
    if (placed.length === 0) return;
    const box = event.currentTarget.ownerSVGElement?.getBoundingClientRect();
    const pointerX = box && box.width > 0 ? ((event.clientX - box.left) / box.width) * width : 0;
    let nearest = 0;
    placed.forEach((point, i) => {
      if (Math.abs(x(point.index) - pointerX) < Math.abs(x(placed[nearest]!.index) - pointerX)) nearest = i;
    });
    setActive(nearest);
  };

  const values = placed.map((p) => p.value);
  const summary = placed.length === 0 ? '관측값 없음'
    : `${placed.length}개 구간 관측, 최솟값 ${formatMetricValue(Math.min(...values), unit)}, 최댓값 ${formatMetricValue(Math.max(...values), unit)}`;

  return (
    <div
      ref={containerRef}
      className="market-chart"
      role="group"
      tabIndex={0}
      aria-label={`${title} 그래프. 좌우 화살표 키로 구간별 값을 확인할 수 있습니다. 같은 값은 아래 표에 있습니다.`}
      onKeyDown={onKeyDown}
      onBlur={() => setActive(null)}
    >
      <svg width={width} height={HEIGHT} viewBox={`0 0 ${width} ${HEIGHT}`} role="img" aria-label={`${title}: ${summary}`}>
        <g className="market-chart-grid" aria-hidden="true">
          {ticks.map((tick) => (
            <g key={tick}>
              <line x1={MARGIN.left} x2={MARGIN.left + plotWidth} y1={y(tick)} y2={y(tick)} />
              <text x={MARGIN.left - 8} y={y(tick)} dy="0.32em" textAnchor="end">{formatAxisValue(tick, unit)}</text>
            </g>
          ))}
          {labelIndexes.map((index, i) => (
            <text key={buckets[index]} x={x(index)} y={HEIGHT - 12}
              textAnchor={buckets.length <= 1 ? 'middle' : i === 0 ? 'start' : i === labelIndexes.length - 1 ? 'end' : 'middle'}>
              {shortLabel(buckets[index]!, period, i === 0)}
            </text>
          ))}
        </g>
        {current && (
          <line className="market-chart-crosshair" aria-hidden="true"
            x1={x(current.index)} x2={x(current.index)} y1={MARGIN.top} y2={MARGIN.top + plotHeight} />
        )}
        <g className="market-chart-series" aria-hidden="true">
          {segments.filter((segment) => segment.length > 1).map((segment) => (
            <path key={segment[0]!.date} d={segment.map((p, i) => `${i ? 'L' : 'M'}${x(p.index)},${y(p.value)}`).join(' ')} />
          ))}
          {placed.map((point, i) => {
            const isolated = segments.some((segment) => segment.length === 1 && segment[0] === point);
            return (
              <circle key={point.date} data-date={point.date} data-value={point.value}
                className={`market-chart-marker${dense && !isolated && i !== active ? ' market-chart-marker--hidden' : ''}${i === active ? ' market-chart-marker--active' : ''}`}
                cx={x(point.index)} cy={y(point.value)} r={i === active ? 6 : 4} />
            );
          })}
        </g>
        <rect className="market-chart-hit" x={MARGIN.left - 8} y={MARGIN.top} width={plotWidth + 16} height={plotHeight}
          onPointerMove={onPointerMove} onPointerLeave={() => setActive(null)} />
      </svg>
      <p className="market-chart-readout" aria-live="polite" data-testid="market-chart-readout">
        {current ? `${periodLabel(current.date, period)}: ${formatMetricValue(current.value, unit)}` : ''}
      </p>
    </div>
  );
}
