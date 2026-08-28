import { useId, useMemo } from 'react';

import type { TrajectoryPreview as TrajectoryPreviewData } from '../../api/types';

const WIDTH = 720;
const HEIGHT = 250;
const PLOT_LEFT = 48;
const PLOT_RIGHT = 704;
const PLOT_TOP = 20;
const PLOT_BOTTOM = 190;
const MAX_SVG_POINTS = 600;
const COLORS = ['#147a99', '#b25926', '#5d5a9d', '#27824a', '#a13c62', '#70631d', '#166f6c', '#7d4a91'];

function boundedPoints<T>(points: T[]): T[] {
  if (points.length <= MAX_SVG_POINTS) return points;
  const stride = Math.ceil(points.length / MAX_SVG_POINTS);
  const sampled = points.filter((_, index) => index % stride === 0);
  if (sampled.at(-1) !== points.at(-1)) sampled.push(points.at(-1) as T);
  return sampled;
}

function range(values: number[]): { minimum: number; maximum: number } {
  if (values.length === 0) return { minimum: 0, maximum: 0 };
  return { minimum: Math.min(...values), maximum: Math.max(...values) };
}

function number(value: number): string {
  return Number.isFinite(value) ? value.toFixed(1) : '—';
}

export function TrajectoryPreview({ preview }: { preview: TrajectoryPreviewData }) {
  const clipId = `trajectory-clip-${useId().replaceAll(':', '')}`;
  const duration = Math.max(preview.duration_s, Number.EPSILON);
  const chart = useMemo(() => {
    const x = (time: number) => PLOT_LEFT + (Math.min(duration, Math.max(0, time)) / duration) * (PLOT_RIGHT - PLOT_LEFT);
    const series = Object.entries(preview.joint_series).map(([jointId, source], index) => {
      const points = boundedPoints(source);
      const values = points.map((point) => point.value);
      const bounds = range(values);
      const span = Math.max(bounds.maximum - bounds.minimum, Number.EPSILON);
      const path = points
        .map((point, pointIndex) => {
          const normalized = (point.value - bounds.minimum) / span;
          const y = PLOT_BOTTOM - normalized * (PLOT_BOTTOM - PLOT_TOP);
          return `${pointIndex === 0 ? 'M' : 'L'} ${x(point.time_s).toFixed(2)} ${y.toFixed(2)}`;
        })
        .join(' ');
      return {
        jointId,
        unit: source[0]?.unit ?? 'deg',
        color: COLORS[index % COLORS.length],
        bounds,
        path,
      };
    });
    const tcp = boundedPoints(preview.tcp_path);
    const xBounds = range(tcp.map((point) => point.x_mm));
    const yBounds = range(tcp.map((point) => point.y_mm));
    const zBounds = range(tcp.map((point) => point.z_mm));
    const xSpan = Math.max(xBounds.maximum - xBounds.minimum, Number.EPSILON);
    const ySpan = Math.max(yBounds.maximum - yBounds.minimum, Number.EPSILON);
    const tcpPath = tcp
      .map((point, index) => {
        const px = 24 + ((point.x_mm - xBounds.minimum) / xSpan) * 192;
        const py = 116 - ((point.y_mm - yBounds.minimum) / ySpan) * 92;
        return `${index === 0 ? 'M' : 'L'} ${px.toFixed(2)} ${py.toFixed(2)}`;
      })
      .join(' ');
    return { series, tcpPath, xBounds, yBounds, zBounds, x };
  }, [duration, preview.joint_series, preview.tcp_path]);

  return (
    <section aria-labelledby="trajectory-preview-heading" className="trajectory-preview">
      <header>
        <div>
          <p className="section-kicker">已准备轨迹</p>
          <h4 id="trajectory-preview-heading">轨迹预览</h4>
        </div>
        <span>{preview.sample_count} 个采样点 · {preview.sample_rate_hz} Hz</span>
      </header>

      <div className="trajectory-preview__layout">
        <figure className="trajectory-chart">
          <figcaption>关节位置随时间变化</figcaption>
          <svg
            aria-label={`${number(preview.duration_s)} 秒关节轨迹`}
            className="trajectory-chart__svg"
            role="img"
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          >
            <defs>
              <clipPath id={clipId}>
                <rect height={PLOT_BOTTOM - PLOT_TOP} width={PLOT_RIGHT - PLOT_LEFT} x={PLOT_LEFT} y={PLOT_TOP} />
              </clipPath>
            </defs>
            <line className="trajectory-chart__axis" x1={PLOT_LEFT} x2={PLOT_LEFT} y1={PLOT_TOP} y2={PLOT_BOTTOM} />
            <line className="trajectory-chart__axis" x1={PLOT_LEFT} x2={PLOT_RIGHT} y1={PLOT_BOTTOM} y2={PLOT_BOTTOM} />
            {[0, 0.25, 0.5, 0.75, 1].map((fraction) => (
              <g key={fraction}>
                <line
                  className="trajectory-chart__grid"
                  x1={PLOT_LEFT + fraction * (PLOT_RIGHT - PLOT_LEFT)}
                  x2={PLOT_LEFT + fraction * (PLOT_RIGHT - PLOT_LEFT)}
                  y1={PLOT_TOP}
                  y2={PLOT_BOTTOM}
                />
                <text className="trajectory-chart__label" textAnchor="middle" x={PLOT_LEFT + fraction * (PLOT_RIGHT - PLOT_LEFT)} y={211}>
                  {number(preview.duration_s * fraction)}s
                </text>
              </g>
            ))}
            <g clipPath={`url(#${clipId})`}>
              {preview.segments.map((segment) => (
                <rect
                  className={`trajectory-chart__segment trajectory-chart__segment--${segment.motion_mode.toLowerCase()}`}
                  height={PLOT_BOTTOM - PLOT_TOP}
                  key={segment.segment_index}
                  width={Math.max(1, chart.x(segment.end_time_s) - chart.x(segment.start_time_s))}
                  x={chart.x(segment.start_time_s)}
                  y={PLOT_TOP}
                >
                  <title>轨迹段 {segment.segment_index + 1} · {segment.motion_mode}</title>
                </rect>
              ))}
              {chart.series.map((series) => (
                <path className="trajectory-chart__path" d={series.path} key={series.jointId} stroke={series.color}>
                  <title>{series.jointId} · {number(series.bounds.minimum)} to {number(series.bounds.maximum)} {series.unit}</title>
                </path>
              ))}
              {preview.keyframe_markers.map((marker) => (
                <line
                  className="trajectory-chart__marker"
                  key={marker.keyframe_id}
                  x1={chart.x(marker.time_s)}
                  x2={chart.x(marker.time_s)}
                  y1={PLOT_TOP}
                  y2={PLOT_BOTTOM}
                >
                  <title>{marker.label} · {number(marker.time_s)} s</title>
                </line>
              ))}
            </g>
            <text className="trajectory-chart__label" x={5} y={17}>归一化</text>
          </svg>
          <ul aria-label="关节轨迹曲线" className="trajectory-chart__legend">
            {chart.series.map((series) => (
              <li key={series.jointId} title={`${series.jointId}: ${series.bounds.minimum}–${series.bounds.maximum} ${series.unit}`}>
                <span aria-hidden="true" style={{ backgroundColor: series.color }} />
                <strong>{series.jointId}</strong>
                <small>{number(series.bounds.minimum)}–{number(series.bounds.maximum)} {series.unit}</small>
              </li>
            ))}
          </ul>
        </figure>

        <figure className="tcp-preview">
          <figcaption>TCP 路径 · 俯视图（X/Y）</figcaption>
          {preview.tcp_path.length > 0 ? (
            <svg aria-label="TCP XY 路径摘要" role="img" viewBox="0 0 240 140">
              <rect className="tcp-preview__frame" height="116" width="216" x="12" y="12" />
              <path className="tcp-preview__path" d={chart.tcpPath} />
            </svg>
          ) : <p>没有 TCP 采样点。</p>}
          <dl>
            <div><dt>X</dt><dd>{number(chart.xBounds.minimum)}–{number(chart.xBounds.maximum)} mm</dd></div>
            <div><dt>Y</dt><dd>{number(chart.yBounds.minimum)}–{number(chart.yBounds.maximum)} mm</dd></div>
            <div><dt>Z</dt><dd>{number(chart.zBounds.minimum)}–{number(chart.zBounds.maximum)} mm</dd></div>
          </dl>
        </figure>
      </div>

      <div className="trajectory-timeline" aria-label="轨迹段与关键帧">
        <div className="trajectory-timeline__segments">
          {preview.segments.map((segment) => (
            <span className={`trajectory-mode trajectory-mode--${segment.motion_mode.toLowerCase()}`} key={segment.segment_index}>
              {segment.motion_mode} · 轨迹段 {segment.segment_index + 1}
            </span>
          ))}
        </div>
        <ol>
          {preview.keyframe_markers.map((marker) => (
            <li key={marker.keyframe_id} title={marker.label}>
              <strong>{marker.label}</strong>
              <span>{number(marker.time_s)} 秒 · 采样点 {marker.sample_index}</span>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
