import { useRuntimeStatus } from '../components/runtimeStatusContext';
import { VisionCanvas } from '../features/vision/VisionCanvas';
import { VisionControls } from '../features/vision/VisionControls';
import { useVisionWorkspace } from '../features/vision/useVisionWorkspace';

export function VisionPage() {
  const runtime = useRuntimeStatus();
  const workspace = useVisionWorkspace(runtime);
  const sourceMode = workspace.capabilities?.camera_access_policy === 'DISABLED'
    ? '图像源已禁用'
    : workspace.capabilities?.source.provider_id.toLowerCase().includes('synthetic')
      ? '合成画面'
      : workspace.capabilities
        ? '实时相机'
        : '等待图像源';
  const sourceOperational = workspace.status?.source_state === 'READY' ||
    workspace.status?.source_state === 'STREAMING';
  const sourceHealthy = workspace.online &&
    workspace.statusReachable &&
    workspace.capabilities?.source.available === true &&
    sourceOperational;
  const sourceId = workspace.capabilities?.source.provider_id ?? '';

  return (
    <div className="page vision-page">
      <header className="vision-page-intro">
        <div>
          <h1>视觉监控</h1>
          <p>{workspace.readOnlyLiveCamera
            ? '预览明确配置的本地相机；不会录像，也不会驱动机械臂。'
            : '选择目标、检查跟踪状态，并通过安全入口执行视觉跟随。'}</p>
        </div>
        <label className={`vision-source-selector${sourceHealthy ? ' vision-source-selector--healthy' : ''}`}>
          <span className="visually-hidden">图像源</span>
          <span aria-hidden="true" className="vision-source-selector__dot" />
          <select
            aria-label="图像源"
            disabled
            title={sourceId ? '后端当前只提供一个已配置图像源' : '正在等待后端图像源'}
            value={sourceId}
          >
            {sourceId ? (
              <option value={sourceId}>{sourceId}</option>
            ) : (
              <option value="">等待图像源</option>
            )}
          </select>
        </label>
      </header>
      <div className="vision-safety-strip" role="status">
        <span>{sourceMode}</span>
        <span>相机策略：{workspace.capabilities?.camera_access_policy ?? '待加载'}</span>
        <span>{workspace.readOnlyLiveCamera
          ? '只读相机'
          : workspace.runtimePolicy === 'READ_ONLY'
            ? '只读'
            : workspace.runtimeMode}</span>
        <span>{workspace.runtimeMode === 'REAL'
          ? workspace.runtimePolicy === 'READ_ONLY'
            ? `只读 · 禁止运动 · ${workspace.realVisionCapability.reason}`
            : workspace.realVisionCapability.allowed
            ? '真机跟随已授权'
            : `真机跟随已阻止 · ${workspace.realVisionCapability.reason}`
          : '真机跟随已阻止'}</span>
      </div>
      <div className="vision-workspace">
        <VisionCanvas workspace={workspace} />
        <VisionControls workspace={workspace} />
      </div>
    </div>
  );
}
