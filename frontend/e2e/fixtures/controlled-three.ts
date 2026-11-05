import type { InteractiveCard } from "../../src/features/answer-ui/interactiveRuntime";

const style = `<style>main{max-width:700px;margin:auto}label{display:inline-flex;flex-direction:column;margin:6px}input{width:76px}canvas{display:block;width:100%;height:240px;border-radius:12px}output{display:block}p{margin:8px 0}</style>`;
const scene = `
const renderer = new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});
renderer.setSize(640,360); renderer.setClearColor(0x14283f); document.querySelector('#scene').append(renderer.domElement);
const scene = new THREE.Scene(); const camera = new THREE.PerspectiveCamera(42,640/360,0.1,100);
camera.position.set(6,5,8); camera.lookAt(0,0,0);
scene.add(new THREE.AmbientLight(0xffffff,2));
const light = new THREE.DirectionalLight(0xffffff,3); light.position.set(4,8,6); scene.add(light);
const mesh = new THREE.Mesh(new THREE.BoxGeometry(1,1,1),new THREE.MeshStandardMaterial({color:0x42d7b4,roughness:0.45})); scene.add(mesh);
const number = id => Number(document.getElementById(id).value);
const render = () => renderer.render(scene,camera);
`;
const wrap = (controls: string, script: string) => `${style}<main><h2>受控 Three.js 实验</h2>${controls}<p id="support" role="status">正在初始化 WebGL2…</p><div id="scene"></div><output id="reading"></output></main><script>
try { if (!document.createElement('canvas').getContext('webgl2')) throw new Error('当前设备不支持 WebGL2，无法运行此实验。');
${scene}
${script}
document.getElementById('support').textContent='WebGL2 已就绪';
} catch(error) { document.getElementById('support').textContent=error.message; document.getElementById('support').dataset.error='true'; }
</script>`;

export const controlledCube: InteractiveCard = {
  type: "interactive", id: "controlled-cube", revision: 1, capabilities: ["three"],
  title: "长方体：尺寸、体积与旋转", summary: "调整长宽高和角度，同一状态驱动 Three.js 模型、体积读值和继续提问状态。",
  html: wrap(`<label>长<input id="length" type="number" min="0.5" max="4" step="0.5" value="2"></label><label>宽<input id="width" type="number" min="0.5" max="4" step="0.5" value="1"></label><label>高<input id="height" type="number" min="0.5" max="4" step="0.5" value="1"></label><label>旋转角度<input id="rotation" type="number" min="0" max="360" value="20"></label>`, `
function update() {
 const state={length:number('length'),width:number('width'),height:number('height'),rotation:number('rotation')};
 state.volume=state.length*state.width*state.height;
 mesh.scale.set(state.length,state.height,state.width); mesh.rotation.y=state.rotation*Math.PI/180; render();
 document.getElementById('reading').textContent='体积 = '+state.volume.toFixed(2);
 window.studyUI.setState(state);
}
document.querySelectorAll('input').forEach(input=>input.addEventListener('input',update)); update();`),
};

export const controlledOscillator: InteractiveCard = {
  type: "interactive", id: "controlled-oscillator", revision: 1, capabilities: ["three"],
  title: "动态过程：简谐运动", summary: "频率与相位决定位置，支持播放、暂停和恢复；x = 2 sin(2πft + φ)。",
  html: wrap(`<label>频率 Hz<input id="frequency" type="number" min="0.1" max="3" step="0.1" value="1"></label><label>相位 rad<input id="phase" type="number" min="-6.28" max="6.28" step="0.1" value="0"></label><button id="play">播放</button>`, `
mesh.scale.setScalar(0.65);
let playing=false,time=0,last=performance.now();
function update() {
 const state={frequency:number('frequency'),phase:number('phase'),time,playing};
 state.position=2*Math.sin(2*Math.PI*state.frequency*time+state.phase);
 mesh.position.x=state.position; render();
 document.getElementById('reading').textContent='t = '+time.toFixed(3)+' s; x = '+state.position.toFixed(3);
 window.studyUI.setState(state);
}
document.getElementById('play').onclick=()=>{playing=!playing;last=performance.now();document.getElementById('play').textContent=playing?'暂停':'播放';update();};
document.querySelectorAll('input').forEach(input=>input.addEventListener('input',update));
function frame(now) {if(playing){time+=(now-last)/1000;update();}last=now;requestAnimationFrame(frame);} update();requestAnimationFrame(frame);`),
};
