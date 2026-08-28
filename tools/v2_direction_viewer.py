#!/usr/bin/env python3
"""Serve a standalone, simulation-only V2 URDF mesh viewer on localhost.

The viewer reads the pinned Legacy V2 URDF/STL assets and browser libraries
from their existing directories. It has no serial, camera, MOMO backend, or
actuator imports and cannot command hardware.
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlsplit
import webbrowser


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_PARENT = ROOT.parent
LEGACY_ROOT = WORKSPACE_PARENT / "MOMO_RobotARM"
LEGACY_URDF = LEGACY_ROOT / "URDF运动学仿真" / "urdf" / "v2" / "soarmoce_urdf.urdf"
LEGACY_MESHES = LEGACY_ROOT / "URDF运动学仿真" / "meshes" / "v2"
VENDOR_ROOT = WORKSPACE_PARENT / "momo-arm" / "web" / "node_modules"
THREE_ROOT = VENDOR_ROOT / "three"
URDF_LOADER_ROOT = VENDOR_ROOT / "urdf-loader"
LEGACY_REVISION = "ff8bbda0c2222cb57951c7913f7f12f5777b98fa"
MESH_ALLOWLIST = {
    "base_link.stl",
    "Link_2.stl",
    "Link_3.stl",
    "Link_4.stl",
    "Link_5.stl",
    "Link_6.stl",
    "Link_7.stl",
}

for required_path in (LEGACY_URDF, THREE_ROOT, URDF_LOADER_ROOT):
    if not required_path.exists():
        raise RuntimeError(f"Required read-only viewer asset is missing: {required_path}")


HTML = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>MOMO V2 独立 3D 模型对照</title>
  <script type="importmap">{{
    "imports": {{
      "three": "/vendor/three/build/three.module.js",
      "three/": "/vendor/three/"
    }}
  }}</script>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; background: #101317; color: #edf2f7; }}
    main {{ display: grid; grid-template-columns: 310px 1fr; min-height: 100vh; gap: 14px; padding: 14px; }}
    aside {{ background: #181d23; border: 1px solid #2a333d; border-radius: 14px; padding: 18px; }}
    h1 {{ font-size: 21px; margin: 0 0 5px; }}
    .safe {{ color: #64d98b; font-weight: 700; line-height: 1.45; margin: 0 0 18px; }}
    .step {{ display: flex; justify-content: space-between; align-items: center; margin: 10px 0 12px; color: #b8c2cc; }}
    select, button {{ font: inherit; }}
    select {{ background: #222932; color: #edf2f7; border: 1px solid #3b4653; border-radius: 7px; padding: 5px 9px; }}
    .joint {{ display: grid; grid-template-columns: 50px 42px 42px 1fr; gap: 6px; align-items: center; border: 1px solid #333d49; background: #222932; border-radius: 8px; margin: 7px 0; padding: 8px; }}
    .joint b {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .joint button {{ border: 0; border-radius: 6px; background: #3a4552; color: white; height: 34px; cursor: pointer; font-size: 20px; }}
    .joint button.plus {{ background: #c84e56; }}
    .joint output {{ text-align: right; color: #cbd4dd; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .reset {{ width: 100%; border: 0; border-radius: 8px; background: #64d98b; color: #101317; padding: 10px; margin-top: 12px; font-weight: 800; cursor: pointer; }}
    .source {{ color: #77828e; font-size: 12px; line-height: 1.5; margin-top: 22px; overflow-wrap: anywhere; }}
    section {{ display: grid; grid-template-rows: auto 1fr; min-width: 0; }}
    header {{ display: flex; justify-content: space-between; align-items: center; min-height: 42px; gap: 10px; }}
    #action {{ color: #f0c96a; font-weight: 750; }}
    .hint {{ color: #86929f; font-size: 12px; }}
    .stage {{ position: relative; min-height: 520px; border: 1px solid #272f39; border-radius: 14px; overflow: hidden; background: #eef2f4; }}
    canvas {{ position: absolute; inset: 0; width: 100%; height: 100%; touch-action: none; }}
    .badge {{ position: absolute; left: 16px; top: 14px; color: #31404b; background: #ffffffd9; padding: 7px 10px; border-radius: 8px; font-size: 12px; box-shadow: 0 4px 18px #15202b24; }}
    .notice {{ position: absolute; left: 16px; bottom: 14px; color: #596976; background: #ffffffd9; padding: 6px 9px; border-radius: 7px; font-size: 12px; }}
    .loading {{ position: absolute; inset: 0; display: grid; place-items: center; color: #52616c; font-weight: 700; pointer-events: none; }}
    .loading[hidden] {{ display: none; }}
    .loading.error {{ color: #a7353e; }}
    @media (max-width: 850px) {{ main {{ grid-template-columns: 1fr; }} aside {{ order: 2; }} .stage {{ min-height: 500px; }} }}
  </style>
</head>
<body>
<main>
  <aside>
    <h1>MOMO V2 真实外形预览</h1>
    <p class="safe">SIMULATION ONLY<br>URDF + STL 三维模型 · 不连接串口 · 不控制实体</p>
    <label class="step">仿真步长
      <select id="step"><option>1</option><option>5</option><option>10</option></select>
    </label>
    <div id="joints"></div>
    <button class="reset" id="reset">回到仿真零位</button>
    <p class="source">来源：只读 Legacy V2 URDF/STL<br>提交：{LEGACY_REVISION[:12]}<br>鼠标左键旋转 · 滚轮缩放 · 右键平移</p>
  </aside>
  <section>
    <header>
      <span id="action">正在加载 V2 三维模型…</span>
      <span class="hint">实体小步仍只在 MOMO 页面由你亲自触发</span>
    </header>
    <div class="stage" id="stage">
      <canvas id="canvas" aria-label="MOMO V2 URDF 三维模型"></canvas>
      <span class="badge">3D URDF VIEW · 可旋转 / 缩放 / 平移</span>
      <span class="notice">Legacy 网格只读预览 · 不代表碰撞验收或正式标定</span>
      <div class="loading" id="loading">加载七个 STL 零件中…</div>
    </div>
  </section>
</main>
<script type="module">
import * as THREE from 'three';
import {{ OrbitControls }} from '/vendor/three/examples/jsm/controls/OrbitControls.js';
import URDFLoader from '/vendor/urdf-loader/src/URDFLoader.js';

const JOINTS = ['j10','j11','j12','j13','j14','j15'];
const values = Object.fromEntries(JOINTS.map(id => [id, 0]));
const canvas = document.querySelector('#canvas');
const stage = document.querySelector('#stage');
const loading = document.querySelector('#loading');
const action = document.querySelector('#action');
let robot = null;

const scene = new THREE.Scene();
scene.background = new THREE.Color('#eef2f4');
const camera = new THREE.PerspectiveCamera(38, 1, 0.005, 50);
camera.position.set(1.15, 0.85, 1.25);
const renderer = new THREE.WebGLRenderer({{canvas, antialias: true, preserveDrawingBuffer: true}});
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.target.set(0, 0.28, 0);
controls.minDistance = 0.2;
controls.maxDistance = 5;

scene.add(new THREE.HemisphereLight(0xffffff, 0x52606a, 1.35));
const key = new THREE.DirectionalLight(0xffffff, 1.75);
key.position.set(1.6, 2.4, 1.4);
key.castShadow = true;
scene.add(key);
const fill = new THREE.DirectionalLight(0xb8d4ff, 0.5);
fill.position.set(-1.2, 0.9, -1.4);
scene.add(fill);
const grid = new THREE.GridHelper(1.8, 18, 0x87949c, 0xcbd3d8);
scene.add(grid);

function setRobotJoints() {{
  if (!robot) return;
  robot.setJointValue('J10', values.j10 / 1000);
  JOINTS.slice(1).forEach(id => robot.setJointValue(id.toUpperCase(), THREE.MathUtils.degToRad(values[id])));
}}

function frameRobot() {{
  const bounds = new THREE.Box3().setFromObject(robot);
  const size = bounds.getSize(new THREE.Vector3());
  const scale = 0.82 / Math.max(size.x, size.y, size.z, 0.001);
  robot.scale.setScalar(scale);
  const scaled = new THREE.Box3().setFromObject(robot);
  const center = scaled.getCenter(new THREE.Vector3());
  robot.position.set(-center.x, -scaled.min.y, -center.z);
  const framed = new THREE.Box3().setFromObject(robot);
  const framedCenter = framed.getCenter(new THREE.Vector3());
  const framedSize = framed.getSize(new THREE.Vector3());
  controls.target.copy(framedCenter);
  const radius = Math.max(framedSize.length(), 0.5);
  camera.position.copy(framedCenter).add(new THREE.Vector3(radius * 1.1, radius * 0.8, radius * 1.25));
  camera.near = radius / 100;
  camera.far = radius * 100;
  camera.updateProjectionMatrix();
  controls.update();
}}

const manager = new THREE.LoadingManager();
manager.onLoad = () => {{
  if (!robot) return;
  frameRobot();
  loading.hidden = true;
  action.textContent = 'V2 三维模型已加载 · 当前为仿真零位';
  canvas.dataset.modelLoaded = 'true';
}};
manager.onError = url => {{
  loading.textContent = `模型资源加载失败：${{url}}`;
  loading.classList.add('error');
}};

const loader = new URDFLoader(manager);
loader.parseCollision = false;
loader.load(
  '/legacy/urdf/v2/soarmoce_urdf.urdf',
  loaded => {{
    robot = loaded;
    robot.rotation.x = -Math.PI / 2;
    robot.traverse(object => {{
      if (!(object instanceof THREE.Mesh)) return;
      object.castShadow = true;
      object.receiveShadow = true;
      object.geometry.computeVertexNormals();
      object.material = new THREE.MeshStandardMaterial({{
        color: object.name.includes('visual') ? '#7f8b94' : '#59656d',
        roughness: 0.66,
        metalness: 0.12,
      }});
    }});
    setRobotJoints();
    scene.add(robot);
  }},
  undefined,
  error => {{
    loading.textContent = `V2 URDF 加载失败：${{error?.message ?? error}}`;
    loading.classList.add('error');
  }},
);

function refreshLabels() {{
  for (const [id,value] of Object.entries(values)) {{
    document.querySelector(`[data-output="${{id}}"]`).textContent = `${{value >= 0 ? '+' : ''}}${{value}} ${{id === 'j10' ? 'mm' : '°'}}`;
  }}
}}
function move(id, sign) {{
  const delta = Number(document.querySelector('#step').value) * sign;
  values[id] += delta;
  setRobotJoints();
  action.textContent = `仿真动作：${{id.toUpperCase()}} ${{delta >= 0 ? '+' : ''}}${{delta}} ${{id === 'j10' ? 'mm' : '°'}}`;
  refreshLabels();
}}

const jointHost = document.querySelector('#joints');
for (const id of JOINTS) {{
  const row = document.createElement('div');
  row.className = 'joint';
  row.innerHTML = `<b>${{id.toUpperCase()}}</b><button aria-label="${{id}} minus">−</button><button class="plus" aria-label="${{id}} plus">+</button><output data-output="${{id}}"></output>`;
  row.children[1].onclick = () => move(id, -1);
  row.children[2].onclick = () => move(id, 1);
  jointHost.append(row);
}}
document.querySelector('#reset').onclick = () => {{
  JOINTS.forEach(id => values[id] = 0);
  setRobotJoints();
  refreshLabels();
  action.textContent = '已回到 V2 仿真零位';
}};
refreshLabels();

const resize = () => {{
  const width = stage.clientWidth;
  const height = stage.clientHeight;
  renderer.setSize(width, height, false);
  camera.aspect = width / Math.max(height, 1);
  camera.updateProjectionMatrix();
}};
new ResizeObserver(resize).observe(stage);
resize();
renderer.setAnimationLoop(() => {{ controls.update(); renderer.render(scene, camera); }});
</script>
</body>
</html>
"""


def _safe_child(root: Path, relative: str) -> Path | None:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


class ViewerHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = unquote(urlsplit(self.path).path)
        file_path: Path | None = None
        if path in {"/", "/index.html"}:
            self._send_bytes(HTML.encode(), "text/html; charset=utf-8")
            return
        if path == "/legacy/urdf/v2/soarmoce_urdf.urdf":
            file_path = LEGACY_URDF
        elif path.startswith("/meshes/v2/") or path.startswith("/legacy/meshes/v2/"):
            mesh_name = path.rsplit("/", 1)[-1]
            if mesh_name in MESH_ALLOWLIST:
                file_path = LEGACY_MESHES / mesh_name
        elif path.startswith("/vendor/three/"):
            file_path = _safe_child(THREE_ROOT, path.removeprefix("/vendor/three/"))
        elif path.startswith("/vendor/urdf-loader/"):
            file_path = _safe_child(
                URDF_LOADER_ROOT,
                path.removeprefix("/vendor/urdf-loader/"),
            )
        if file_path is None or not file_path.is_file():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        if file_path.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        self._send_bytes(file_path.read_bytes(), content_type)

    def _send_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
            "img-src 'self' data:; object-src 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), ViewerHandler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"MOMO V2 simulation-only URDF viewer: {url}", flush=True)
    print(f"Legacy source: {LEGACY_URDF} @ {LEGACY_REVISION}", flush=True)
    if not args.no_open:
        webbrowser.open(url, new=1)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
