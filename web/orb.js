// Frosted glass sphere holding a twisting violet ribbon: the "residual" left after market and sector are removed.
import * as THREE from "three";

const canvas = document.getElementById("orb");
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

let renderer;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  if (!renderer.getContext()) throw new Error("no webgl");
} catch (e) {
  document.documentElement.classList.add("no-webgl");
  throw e;
}
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.0;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.setClearColor(0x000000, 0);

// Studio environment: lavender gradient dome plus white softboxes -> soft lilac reflections, no dark room
function studio() {
  const env = new THREE.Scene();
  const dome = new THREE.Mesh(new THREE.SphereGeometry(10, 48, 32), new THREE.ShaderMaterial({
    side: THREE.BackSide,
    vertexShader: "varying vec3 vP; void main(){ vP = normalize(position); gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }",
    fragmentShader: `varying vec3 vP;
      void main(){
        float h = vP.y*0.5+0.5;
        vec3 low = vec3(0.62,0.52,0.98), mid = vec3(0.90,0.87,0.98), top = vec3(1.0);
        vec3 c = mix(low, mid, smoothstep(0.0,0.55,h)); c = mix(c, top, smoothstep(0.55,1.0,h));
        gl_FragColor = vec4(c,1.0);
      }`,
  }));
  env.add(dome);
  const box = (w, h, x, y, z, s = 3) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: new THREE.Color(s, s, s), side: THREE.DoubleSide }));
    m.position.set(x, y, z); m.lookAt(0, 0, 0); env.add(m);
  };
  box(4, 2.4, -4, 5, 5, 4);      // key softbox, upper left
  box(2, 5, 6, 1, 2, 2);         // side strip
  box(6, 1, 0, -6, 3, 1.2);      // floor bounce
  return new THREE.PMREMGenerator(renderer).fromScene(env, 0.02).texture;
}

const scene = new THREE.Scene();
const envMap = studio();

const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 50);
camera.position.set(0, 0, 6.2);

const rig = new THREE.Group();
scene.add(rig);

// ribbon: a twisted band swept along a tilted loop
function ribbonGeometry(segments = 480, width = 0.7, radius = 0.64) {
  const pos = [], nrm = [], uv = [], idx = [];
  const up = new THREE.Vector3(0, 1, 0);
  for (let i = 0; i <= segments; i++) {
    const u = i / segments, a = u * Math.PI * 2;
    const c = new THREE.Vector3(Math.cos(a) * radius, Math.sin(a * 2) * 0.24, Math.sin(a) * radius);
    const tangent = new THREE.Vector3(-Math.sin(a) * radius, Math.cos(a * 2) * 0.48, Math.cos(a) * radius).normalize();
    const outward = new THREE.Vector3(c.x, 0, c.z).normalize();
    const twist = a * 1.5;
    const side = outward.clone().multiplyScalar(Math.cos(twist)).addScaledVector(up, Math.sin(twist)).normalize();
    const n = new THREE.Vector3().crossVectors(tangent, side).normalize();
    const w = width * (0.45 + 0.55 * Math.sin(a + 0.6) ** 2);
    for (const s of [-1, 1]) {
      const p = c.clone().addScaledVector(side, (s * w) / 2);
      pos.push(p.x, p.y, p.z); nrm.push(n.x, n.y, n.z); uv.push(u, s < 0 ? 0 : 1);
    }
    if (i < segments) { const k = i * 2; idx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2); }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("normal", new THREE.Float32BufferAttribute(nrm, 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(idx);
  return g;
}

// Ribbon color is authored, not lit: deep violet along the band into lilac, with a soft
// fresnel sheen and a moving highlight, so the shell above it can never bleach it grey.
const ribbon = new THREE.Mesh(ribbonGeometry(), new THREE.ShaderMaterial({
  side: THREE.DoubleSide, transparent: true,
  uniforms: { uTime: { value: 0 } },
  vertexShader: `varying vec2 vUv; varying vec3 vN; varying vec3 vV;
    void main(){ vUv = uv; vN = normalize(normalMatrix*normal);
      vV = normalize(-(modelViewMatrix*vec4(position,1.0)).xyz);
      gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
  fragmentShader: `varying vec2 vUv; varying vec3 vN; varying vec3 vV; uniform float uTime;
    void main(){
      vec3 deep = vec3(0.36,0.20,0.95), mid = vec3(0.56,0.42,1.0), lilac = vec3(0.86,0.80,1.0);
      float band = 0.5 + 0.5*sin(vUv.x*6.2831*1.5 + uTime*0.6);
      vec3 c = mix(deep, mid, band);
      float edge = smoothstep(0.0, 0.5, abs(vUv.y - 0.5));
      c = mix(c, lilac, edge*0.55);
      float facing = abs(dot(normalize(vN), vV));
      float sheen = pow(1.0 - facing, 3.0);
      float hl = pow(max(0.0, sin(vUv.x*6.2831 - uTime*0.8)), 24.0);
      c += vec3(0.9,0.85,1.0) * (sheen*0.45 + hl*0.35);
      gl_FragColor = vec4(c, 0.96);
    }`,
}));
ribbon.rotation.set(0.55, 0, -0.4);
ribbon.renderOrder = 1;
rig.add(ribbon);

// frosted shell: fresnel rim + lilac body, drawn after the ribbon so the ribbon reads through it
const shellMat = new THREE.ShaderMaterial({
  transparent: true, depthWrite: false,
  uniforms: { uTime: { value: 0 } },
  vertexShader: `varying vec3 vN; varying vec3 vV; varying vec3 vW;
    void main(){ vec4 wp = modelMatrix*vec4(position,1.0); vW = wp.xyz;
      vN = normalize(normalMatrix*normal); vV = normalize(-(modelViewMatrix*vec4(position,1.0)).xyz);
      gl_Position = projectionMatrix*viewMatrix*wp; }`,
  fragmentShader: `varying vec3 vN; varying vec3 vV; varying vec3 vW; uniform float uTime;
    void main(){
      float f = pow(1.0 - max(dot(vN, vV), 0.0), 2.2);
      vec3 body = mix(vec3(0.93,0.90,1.0), vec3(0.80,0.72,1.0), smoothstep(-1.0, 1.0, -vW.y + vW.x*0.4));
      vec3 rim = vec3(1.0);
      vec3 c = mix(body, rim, f);
      float spec = pow(max(dot(reflect(-vV, vN), normalize(vec3(-0.5,0.7,0.6))), 0.0), 60.0);
      float a = 0.10 + f*0.70 + spec*0.6;
      gl_FragColor = vec4(c + spec, clamp(a, 0.0, 0.95));
    }`,
});
const shell = new THREE.Mesh(new THREE.SphereGeometry(1, 128, 96), shellMat);
shell.renderOrder = 2;
rig.add(shell);

// glossy highlight layer on the shell
const gloss = new THREE.Mesh(new THREE.SphereGeometry(1.001, 96, 64), new THREE.MeshPhysicalMaterial({
  color: 0xffffff, roughness: 0.08, metalness: 0, envMap, envMapIntensity: 1.1, transparent: true, opacity: 0.18,
  clearcoat: 1, clearcoatRoughness: 0.03, depthWrite: false,
}));
gloss.material.opacity = 0.08;
gloss.renderOrder = 3;
rig.add(gloss);

scene.add(new THREE.AmbientLight(0xffffff, 0.6));
const key = new THREE.DirectionalLight(0xffffff, 1.4); key.position.set(-3, 4, 5); scene.add(key);
const rimLight = new THREE.PointLight(0x8f6bff, 14, 12); rimLight.position.set(2.6, -1.6, 1.8); scene.add(rimLight);

function resize() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h; camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(canvas);
resize();

const target = { x: 0, y: 0 }, cur = { x: 0, y: 0 };
addEventListener("pointermove", e => {
  target.x = (e.clientX / innerWidth - 0.5) * 0.5;
  target.y = (e.clientY / innerHeight - 0.5) * 0.35;
});

// only render while the sphere is on screen
let onScreen = true;
new IntersectionObserver(es => { onScreen = es[0].isIntersecting; }, { threshold: 0 }).observe(canvas);

const clock = new THREE.Clock();
function frame() {
  requestAnimationFrame(frame);
  if (!onScreen) return;
  const t = clock.getElapsedTime(), k = reduce ? 0 : 1;
  cur.x += (target.x - cur.x) * 0.04; cur.y += (target.y - cur.y) * 0.04;
  rig.rotation.y = cur.x + Math.sin(t * 0.2) * 0.15 * k;
  rig.rotation.x = cur.y + Math.sin(t * 0.35) * 0.06 * k;
  ribbon.rotation.y = t * 0.3 * k;
  ribbon.rotation.z = -0.4 + Math.sin(t * 0.5) * 0.14 * k;
  rig.position.y = Math.sin(t * 0.8) * 0.05 * k;
  shellMat.uniforms.uTime.value = t;
  ribbon.material.uniforms.uTime.value = t * k;
  renderer.render(scene, camera);
}
frame();
requestAnimationFrame(() => canvas.classList.add("on"));
