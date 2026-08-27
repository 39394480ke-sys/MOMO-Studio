import { PageIntro } from '../components/PageIntro';
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

  return (
    <div className="page vision-page">
      <PageIntro
        title="视觉"
        description={workspace.readOnlyLiveCamera
          ? '预览明确配置的本地相机；不会录像，也不会驱动机械臂。'
          : '选择并跟踪目标，通过后端能力门控执行视觉跟随。'}
        detail={workspace.readOnlyLiveCamera
          ? '只有你主动操作后才会打开相机；目标选择、检测、跟踪和跟随保持禁用。'
          : '画面身份、检测器能力、目标新鲜度和运动安全入口会在每一步保持可见。'}
      />
      <div className="vision-safety-strip" role="status">
        <span>{sourceMode}</span>
        <span>相机策略：{workspace.capabilities?.camera_access_policy ?? '待加载'}</span>
        <span>{workspace.readOnlyLiveCamera
          ? '只读相机'
          : workspace.runtimePolicy === 'READ_ONLY'
            ? '只读'
            : workspace.runtimeMode}</span>
        <span>{workspace.runtimeMode === 'REAL'
          ? workspace.realVisionCapability.allowed
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
