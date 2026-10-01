// 3D globe view. A displaced sphere sculpted from elevation data and shaded
// dark, with aircraft drawn as an HTML overlay projected from lat/lon.
// Exposes window.Globe3D; app.js keeps working on the flat map without it.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Line2 } from 'three/addons/lines/Line2.js';
import { LineGeometry } from 'three/addons/lines/LineGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';

// NASA-derived textures shipped with three-globe (MIT). Equirectangular.
const IMG = 'https://unpkg.com/three-globe@2.31.0/example/img/';
const TOPO_URL = IMG + 'earth-topology.png';    // elevation, ocean = 0
const WATER_URL = IMG + 'earth-water.png';      // water = white
const NIGHT_URL = IMG + 'earth-night.jpg';      // city lights

const DISP = 0.024;          // peak terrain height, in globe radii
const CLEARANCE = 0.007;     // how far aircraft and trails float above terrain
const DEG = Math.PI / 180;
const NM_PER_RAD = 3440.065;

const host = document.getElementById('globe');
const overlay = document.createElement('div');
overlay.className = 'goverlay';

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
host.appendChild(renderer.domElement);
host.appendChild(overlay);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 200);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enablePan = false;
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.minDistance = 1.15;
controls.maxDistance = 7;
// OrbitControls' wheel zoom divides by devicePixelRatio, which makes a Retina
// mouse notch move the camera about 2%. Zoom is handled below instead.
controls.enableZoom = false;
controls.autoRotate = true;
controls.autoRotateSpeed = 0.3;

// ------------------------------------------------------------------ geometry
function latLonToVec3(lat, lon, r) {
  const la = lat * DEG, lo = lon * DEG, c = Math.cos(la);
  return new THREE.Vector3(c * Math.cos(lo) * r, Math.sin(la) * r,
                           -c * Math.sin(lo) * r);
}

function vec3ToLatLon(v) {
  const n = v.clone().normalize();
  return { lat: Math.asin(n.y) / DEG, lng: Math.atan2(-n.z, n.x) / DEG };
}

// Point reached from (lat, lon) after `deg` of arc on bearing `track`.
function advance(lat, lon, track, deg) {
  const p = lat * DEG, l = lon * DEG, b = (track || 0) * DEG, d = deg * DEG;
  const p2 = Math.asin(Math.sin(p) * Math.cos(d)
                       + Math.cos(p) * Math.sin(d) * Math.cos(b));
  const l2 = l + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p),
                            Math.cos(d) - Math.sin(p) * Math.sin(p2));
  return [p2 / DEG, l2 / DEG];
}

// CPU copy of the elevation map so markers can sit on the terrain.
let heights = null;
const HW = 1024, HH = 512;
function heightAt(lat, lon) {
  if (!heights) return 0;
  const x = Math.min(HW - 1, Math.max(0, Math.floor((lon + 180) / 360 * HW)));
  const y = Math.min(HH - 1, Math.max(0, Math.floor((90 - lat) / 180 * HH)));
  return heights[(y * HW + x) * 4] / 255;
}
function surface(lat, lon) {
  return latLonToVec3(lat, lon, 1 + DISP * heightAt(lat, lon) + CLEARANCE);
}

// --------------------------------------------------------------------- earth
const loader = new THREE.TextureLoader();
function tex(url) {
  const t = loader.load(url);
  t.wrapS = THREE.RepeatWrapping;
  t.anisotropy = renderer.capabilities.getMaxAnisotropy();
  return t;
}

const earthMat = new THREE.ShaderMaterial({
  uniforms: {
    tTopo: { value: tex(TOPO_URL) },
    tWater: { value: tex(WATER_URL) },
    tNight: { value: tex(NIGHT_URL) },
    uDisp: { value: DISP },
    uTexel: { value: new THREE.Vector2(1 / 2048, 1 / 1024) },
    uRelief: { value: 13.0 },
    uLights: { value: 1.0 },
  },
  vertexShader: /* glsl */`
    uniform sampler2D tTopo;
    uniform float uDisp;
    varying vec2 vUv;
    varying vec3 vN, vE, vNr, vViewPos;
    void main() {
      vUv = uv;
      vec3 n = normalize(position);
      // Local east/north on the sphere, for relief shading in the fragment.
      vec3 e = normalize(vec3(n.z, 0.0, -n.x) + vec3(1e-6, 0.0, 0.0));
      vN = normalMatrix * n;
      vE = normalMatrix * e;
      vNr = normalMatrix * cross(n, e);
      float h = texture2D(tTopo, uv).r;
      vec4 mv = modelViewMatrix * vec4(n * (1.0 + h * uDisp), 1.0);
      vViewPos = mv.xyz;
      gl_Position = projectionMatrix * mv;
    }`,
  fragmentShader: /* glsl */`
    uniform sampler2D tTopo, tWater, tNight;
    uniform vec2 uTexel;
    uniform float uRelief, uLights;
    varying vec2 vUv;
    varying vec3 vN, vE, vNr, vViewPos;
    const vec3 ACCENT = vec3(0.31, 0.71, 0.76);
    void main() {
      float h = texture2D(tTopo, vUv).r;
      float hE = texture2D(tTopo, vUv + vec2(uTexel.x, 0.0)).r
               - texture2D(tTopo, vUv - vec2(uTexel.x, 0.0)).r;
      float hN = texture2D(tTopo, vUv + vec2(0.0, uTexel.y)).r
               - texture2D(tTopo, vUv - vec2(0.0, uTexel.y)).r;
      float coslat = max(sin(vUv.y * 3.14159265), 0.08);

      vec3 sN = normalize(vN);
      vec3 rN = normalize(sN - uRelief * (hE / coslat * normalize(vE)
                                          + hN * normalize(vNr)));
      vec3 V = normalize(-vViewPos);
      vec3 L = normalize(vec3(-0.55, 0.6, 0.6));   // fixed to the camera
      vec3 H = normalize(L + V);
      float diff = max(dot(rN, L), 0.0);
      float sdiff = max(dot(sN, L), 0.0);

      float w = texture2D(tWater, vUv).r;
      float water = smoothstep(0.35, 0.65, w);

      vec3 land = mix(vec3(0.060, 0.092, 0.122), vec3(0.235, 0.300, 0.345),
                      pow(h, 0.65));
      land *= 0.38 + 1.15 * diff;
      land += ACCENT * pow(max(dot(rN, H), 0.0), 22.0) * 0.07;

      vec3 ocean = vec3(0.016, 0.030, 0.046) * (0.55 + 0.9 * sdiff);
      ocean += ACCENT * pow(max(dot(sN, H), 0.0), 38.0) * 0.10;

      vec3 col = mix(land, ocean, water);

      // Coastline glow from the soft edge of the water mask.
      float coast = pow(max(1.0 - abs(w - 0.5) * 2.0, 0.0), 2.0);
      col += ACCENT * coast * 0.20;

      // City lights. The backdrop of this image is blue with almost no red,
      // so the red channel alone isolates the lit pixels.
      float lights = smoothstep(0.09, 0.45, texture2D(tNight, vUv).r);
      col += vec3(1.0, 0.72, 0.40) * lights * (1.0 - water) * uLights;

      // Graticule every 15 degrees.
      vec2 g = vec2(vUv.x * 24.0, vUv.y * 12.0);
      vec2 gl = abs(fract(g - 0.5) - 0.5) / fwidth(g);
      col += ACCENT * (1.0 - min(min(gl.x, gl.y), 1.0)) * 0.05;

      // Limb glow.
      col += ACCENT * pow(1.0 - max(dot(sN, V), 0.0), 3.0) * 0.38;

      gl_FragColor = vec4(col, 1.0);
    }`,
});
const earth = new THREE.Mesh(new THREE.SphereGeometry(1, 512, 256), earthMat);
scene.add(earth);

const atmosphere = new THREE.Mesh(
  new THREE.SphereGeometry(1.16, 96, 48),
  new THREE.ShaderMaterial({
    side: THREE.BackSide, transparent: true, depthWrite: false,
    blending: THREE.AdditiveBlending,
    vertexShader: /* glsl */`
      varying vec3 vN;
      void main() {
        vN = normalize(normalMatrix * normal);
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }`,
    fragmentShader: /* glsl */`
      varying vec3 vN;
      void main() {
        float i = pow(clamp(-vN.z / 0.52, 0.0, 1.0), 2.4);
        gl_FragColor = vec4(vec3(0.31, 0.71, 0.76) * i * 0.75, i);
      }`,
  }));
scene.add(atmosphere);

(function addStars() {
  const n = 2600, pos = new Float32Array(n * 3), col = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const v = new THREE.Vector3().randomDirection().multiplyScalar(80);
    pos.set([v.x, v.y, v.z], i * 3);
    const b = 0.25 + Math.random() * 0.75;
    col.set([b * 0.85, b * 0.93, b], i * 3);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
  scene.add(new THREE.Points(geo, new THREE.PointsMaterial({
    size: 1.4, sizeAttenuation: false, vertexColors: true,
    transparent: true, opacity: 0.8, depthWrite: false })));
})();

// ------------------------------------------------------------------- markers
// {el, plane, lat, lon, track, pos}
const tracked = new Map();
let nearby = [];
const trails = new Map();          // key -> {line, n, colour}
let popup = null;                  // {el, lat, lon, pos}
let onSelect = () => {};
let dirty = true;

const SVG_NS = 'http://www.w3.org/2000/svg';
function planeEl(size, colour) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 26 26');
  svg.setAttribute('width', size);
  svg.setAttribute('height', size);
  const path = document.createElementNS(SVG_NS, 'path');
  path.setAttribute('d', 'M13 1 L18 16 L13 13 L8 16 Z');
  path.setAttribute('fill', colour);
  path.setAttribute('stroke', '#080c11');
  path.setAttribute('stroke-width', '1');
  path.setAttribute('stroke-linejoin', 'round');
  svg.appendChild(path);
  return svg;
}

function makeMarker(cls, size, colour, label) {
  const el = document.createElement('div');
  el.className = 'gmark ' + cls;
  const plane = planeEl(size, colour);
  el.appendChild(plane);
  if (label) {
    const tag = document.createElement('span');
    tag.className = 'tag';
    tag.textContent = label;
    el.appendChild(tag);
  }
  overlay.appendChild(el);
  return { el, plane };
}

function place(m) {
  m.pos = surface(m.lat, m.lon);
  const [la, lo] = advance(m.lat, m.lon, m.track, 0.4);
  m.ahead = surface(la, lo);
}

function trailPositions(points) {
  const out = [];
  let prev = null;
  for (const [lat, lon] of points) {
    const v = latLonToVec3(lat, lon, 1);
    if (prev) {
      // Subdivide long hops so the line follows the curve, not a chord.
      const steps = Math.min(64, Math.floor(prev.angleTo(v) / (0.5 * DEG)));
      for (let i = 1; i < steps; i++) {
        const ll = vec3ToLatLon(prev.clone().lerp(v, i / steps));
        const s = surface(ll.lat, ll.lng);
        out.push(s.x, s.y, s.z);
      }
    }
    const s = surface(lat, lon);
    out.push(s.x, s.y, s.z);
    prev = v;
  }
  return out;
}

function setTrail(key, points, colour) {
  let t = trails.get(key);
  if (!points || points.length < 2) {
    if (t) { scene.remove(t.line); t.line.geometry.dispose(); trails.delete(key); }
    return;
  }
  if (t && t.n === points.length && t.topo === !!heights) {
    if (t.colour !== colour) { t.line.material.color.set(colour); t.colour = colour; }
    return;
  }
  if (t) { scene.remove(t.line); t.line.geometry.dispose(); t.line.material.dispose(); }
  const geo = new LineGeometry();
  geo.setPositions(trailPositions(points));
  const mat = new LineMaterial({ color: colour, linewidth: 2.4,
                                 transparent: true, opacity: 0.9 });
  mat.resolution.set(host.clientWidth || 1, host.clientHeight || 1);
  const line = new Line2(geo, mat);
  scene.add(line);
  trails.set(key, { line, n: points.length, colour, topo: !!heights });
}

function flightColour(f, selectedKey) {
  return f.emergency ? '#e0574d' : (selectedKey === f.key ? '#4fb6c2' : '#9db6c9');
}

function setTracked(flights, selectedKey) {
  const live = new Set();
  for (const f of flights) {
    live.add(f.key);
    const colour = flightColour(f, selectedKey);
    setTrail(f.key, f.trail, colour);
    if (f.lat == null || f.lon == null) continue;
    let m = tracked.get(f.key);
    if (!m) {
      m = makeMarker('tracked', 30, colour, f.callsign);
      m.el.addEventListener('click', () => onSelect(f.key));
      tracked.set(f.key, m);
    }
    m.plane.firstChild.setAttribute('fill', colour);
    m.el.classList.toggle('sel', selectedKey === f.key);
    m.lat = f.lat; m.lon = f.lon; m.track = f.track_deg;
    place(m);
  }
  for (const [key, m] of tracked) {
    if (!live.has(key)) { m.el.remove(); tracked.delete(key); }
  }
  for (const key of [...trails.keys()]) {
    if (!live.has(key)) setTrail(key, null);
  }
  dirty = true;
}

function clearNearby() {
  for (const m of nearby) m.el.remove();
  nearby = [];
}

// list: [{lat, lon, track, colour, html}]
function setNearby(list) {
  clearNearby();
  for (const a of list) {
    if (a.lat == null || a.lon == null) continue;
    const m = makeMarker('near', 18, a.colour);
    m.lat = a.lat; m.lon = a.lon; m.track = a.track;
    m.el.addEventListener('click', () => showPopup(a.lat, a.lon, a.html));
    place(m);
    nearby.push(m);
  }
  dirty = true;
}

// ------------------------------------------------------------ flight history
// Two independent sets of routes: the user's own, and one mate's.
function routeLayer(colour, dotClass) {
  return { colour, dotClass, routes: [], line: null, dots: [] };
}
const layers = {
  mine: routeLayer('#5fd0dd', 'gdot'),
  mate: routeLayer('#f08a6b', 'gdot mate'),
};

// Great-circle arc from a to b ([lat, lon]) that lifts off the surface in the
// middle, returned as segment pairs for one batched line.
function arcSegments(a, b, out) {
  const va = latLonToVec3(a[0], a[1], 1), vb = latLonToVec3(b[0], b[1], 1);
  const angle = va.angleTo(vb);
  const ra = surface(a[0], a[1]).length(), rb = surface(b[0], b[1]).length();
  const lift = Math.min(0.22, Math.max(0.02, angle * 0.11));
  const axis = new THREE.Vector3().crossVectors(va, vb);
  // Antipodal airports have no unique great circle; pick any perpendicular.
  if (axis.lengthSq() < 1e-10) axis.set(0, 1, 0).cross(va);
  axis.normalize();
  const steps = Math.max(8, Math.ceil(angle / (2.5 * DEG)));
  let prev = null;
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const p = va.clone().applyAxisAngle(axis, angle * t)
      .multiplyScalar(ra + (rb - ra) * t + lift * Math.sin(Math.PI * t));
    if (prev) out.push(prev.x, prev.y, prev.z, p.x, p.y, p.z);
    prev = p;
  }
}

function buildLine(layer) {
  if (layer.line) {
    scene.remove(layer.line);
    layer.line.geometry.dispose();
    layer.line.material.dispose();
    layer.line = null;
  }
  if (!layer.routes.length) return;
  const positions = [];
  for (const r of layer.routes) arcSegments(r.a, r.b, positions);
  const geo = new LineSegmentsGeometry();
  geo.setPositions(positions);
  // Opaque on purpose: segment ends overlap, and any blending beads the line.
  const mat = new LineMaterial({ color: layer.colour, linewidth: 1.8 });
  mat.resolution.set(w || 1, h || 1);
  layer.line = new LineSegments2(geo, mat);
  scene.add(layer.line);
}

// routes: [{a: [lat, lon], b: [lat, lon]}], one per distinct airport pair.
// airports: [{lat, lon, code, name}]
function setLayer(layer, routes, airports) {
  layer.routes = routes;
  buildLine(layer);
  for (const d of layer.dots) d.el.remove();
  layer.dots = airports.map(a => {
    const el = document.createElement('div');
    el.className = layer.dotClass;
    const tag = document.createElement('span');
    tag.className = 'tag';
    tag.textContent = a.code;
    el.title = a.name || a.code;
    el.appendChild(tag);
    overlay.appendChild(el);
    return { el, lat: a.lat, lon: a.lon, pos: surface(a.lat, a.lon) };
  });
  dirty = true;
}
const setRoutes = (routes, airports) => setLayer(layers.mine, routes, airports);
const setMateRoutes = (routes, airports) => setLayer(layers.mate, routes, airports);

// Frame both ends of a route.
function flyToRoute(a, b) {
  const va = latLonToVec3(a[0], a[1], 1), vb = latLonToVec3(b[0], b[1], 1);
  const mid = va.clone().add(vb);
  if (mid.lengthSq() < 1e-6) mid.copy(va);
  const ll = vec3ToLatLon(mid);
  flyTo(ll.lat, ll.lng, Math.min(4.2, Math.max(1.7, 1.5 + va.angleTo(vb) * 1.25)));
}

function closePopup() {
  if (popup) { popup.el.remove(); popup = null; }
}

function showPopup(lat, lon, html) {
  closePopup();
  const el = document.createElement('div');
  el.className = 'gpop';
  el.innerHTML = html;
  const x = document.createElement('button');
  x.className = 'gpop-x';
  x.textContent = '×';
  x.addEventListener('click', closePopup);
  el.appendChild(x);
  overlay.appendChild(el);
  popup = { el, lat, lon, pos: surface(lat, lon) };
  dirty = true;
}

// -------------------------------------------------------------------- camera
let fly = null;

function stopIdleSpin() { controls.autoRotate = false; }

// Wheel and pinch zoom: each event scales the target distance, and the camera
// eases toward it so a notch feels immediate but not jumpy.
let targetDist = 3.3;
const WHEEL_K = 0.0016;     // per pixel of scroll; a 100px notch is about 17%
const PINCH_K = 0.012;      // trackpad pinch arrives as small ctrl+wheel deltas
renderer.domElement.addEventListener('wheel', e => {
  e.preventDefault();
  const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
  const d = Math.max(-150, Math.min(150, e.deltaY * unit));
  targetDist = Math.min(controls.maxDistance, Math.max(controls.minDistance,
    targetDist * Math.exp(d * (e.ctrlKey ? PINCH_K : WHEEL_K))));
  fly = null;
}, { passive: false });

let lastFrame = 0;
function stepZoom(now) {
  const dt = Math.min(0.1, (now - lastFrame) / 1000);
  lastFrame = now;
  const cur = camera.position.length();
  if (fly) { targetDist = cur; return; }   // a camera flight owns the distance
  if (Math.abs(targetDist - cur) < 1e-4) return;
  camera.position.setLength(cur + (targetDist - cur) * (1 - Math.exp(-dt * 16)));
}
renderer.domElement.addEventListener('pointerdown', () => { stopIdleSpin(); fly = null; });
renderer.domElement.addEventListener('wheel', stopIdleSpin, { passive: true });

function lookFrom(lat, lon, dist) {
  camera.position.copy(latLonToVec3(lat, lon, dist));
  camera.lookAt(0, 0, 0);
}

function flyTo(lat, lon, dist) {
  stopIdleSpin();
  const d0 = camera.position.length();
  fly = {
    from: camera.position.clone().normalize(),
    to: latLonToVec3(lat, lon, 1),
    d0, d1: dist || Math.min(d0, 2.1),
    t0: performance.now(), ms: 1100,
  };
}

function stepFly(now) {
  if (!fly) return;
  const k = Math.min(1, (now - fly.t0) / fly.ms);
  const e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
  const q = new THREE.Quaternion().setFromUnitVectors(fly.from, fly.to);
  const dir = fly.from.clone().applyQuaternion(
    new THREE.Quaternion().slerp(q, e));
  // Pull back mid-flight on long hops so the globe reads as a globe.
  const arc = fly.from.angleTo(fly.to);
  const lift = Math.sin(Math.PI * e) * Math.min(1.2, arc * 0.5);
  camera.position.copy(dir.multiplyScalar(
    fly.d0 + (fly.d1 - fly.d0) * e + lift));
  if (k >= 1) { fly = null; targetDist = camera.position.length(); }
}

function getCenter() { return vec3ToLatLon(camera.position); }

// Roughly how much ground the view covers, as a radius in nautical miles.
function viewRadiusNm() {
  const d = camera.position.length();
  return Math.min(Math.PI / 2, (d - 1) * Math.tan(camera.fov * DEG / 2))
         * NM_PER_RAD;
}

// --------------------------------------------------------------------- frame
const proj = new THREE.Vector3();
let w = 0, h = 0;
const lastCam = new THREE.Vector3();

function resize() {
  const nw = host.clientWidth, nh = host.clientHeight;
  if (!nw || !nh || (nw === w && nh === h)) return;
  w = nw; h = nh;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  // Keep the whole globe in frame on tall, narrow screens.
  camera.fov = w < h ? Math.min(70, 38 * h / w) : 38;
  camera.updateProjectionMatrix();
  for (const t of trails.values()) t.line.material.resolution.set(w, h);
  for (const layer of Object.values(layers)) {
    if (layer.line) layer.line.material.resolution.set(w, h);
  }
  dirty = true;
}

function toScreen(v) {
  proj.copy(v).project(camera);
  return [(proj.x + 1) / 2 * w, (1 - proj.y) / 2 * h];
}

function layoutMarker(m, camDir, horizon) {
  if (!m.pos || m.pos.clone().normalize().dot(camDir) < horizon) {
    m.el.style.display = 'none';
    return;
  }
  const [x, y] = toScreen(m.pos);
  const [ax, ay] = toScreen(m.ahead);
  const rot = Math.atan2(ax - x, -(ay - y)) / DEG;
  m.el.style.display = '';
  m.el.style.transform = `translate(${x.toFixed(1)}px,${y.toFixed(1)}px)`;
  m.plane.style.transform = `rotate(${rot.toFixed(1)}deg)`;
}

function layout() {
  const d = camera.position.length();
  const camDir = camera.position.clone().normalize();
  const horizon = 1 / d + 0.02;
  for (const m of tracked.values()) layoutMarker(m, camDir, horizon);
  for (const m of nearby) layoutMarker(m, camDir, horizon);
  for (const m of [...layers.mine.dots, ...layers.mate.dots]) {
    if (m.pos.clone().normalize().dot(camDir) < horizon) {
      m.el.style.display = 'none';
      continue;
    }
    const [x, y] = toScreen(m.pos);
    m.el.style.display = '';
    m.el.style.transform = `translate(${x.toFixed(1)}px,${y.toFixed(1)}px)`;
  }
  if (popup) {
    if (popup.pos.clone().normalize().dot(camDir) < horizon) {
      popup.el.style.display = 'none';
    } else {
      const [x, y] = toScreen(popup.pos);
      popup.el.style.display = '';
      popup.el.style.transform =
        `translate(${x.toFixed(1)}px,${y.toFixed(1)}px) translate(-50%,-100%) translateY(-16px)`;
    }
  }
}

function frame(now) {
  requestAnimationFrame(frame);
  if (host.hidden) return;
  resize();
  if (!w) return;
  stepFly(now);
  stepZoom(now);
  // Slower drag when zoomed in, so a degree of mouse is a degree of ground.
  controls.rotateSpeed = Math.min(1, Math.max(0.03, (camera.position.length() - 1) * 0.45));
  controls.update();
  // Dim the city lights up close, where they compete with aircraft markers.
  earthMat.uniforms.uLights.value = THREE.MathUtils.clamp(
    (camera.position.length() - 1.5) / 1.1, 0.3, 1);
  renderer.render(scene, camera);
  if (dirty || !lastCam.equals(camera.position)) {
    layout();
    lastCam.copy(camera.position);
    dirty = false;
  }
}

// Load the elevation map again as pixels so markers can follow the terrain.
(function loadHeights() {
  const img = new Image();
  img.crossOrigin = 'anonymous';
  img.onload = () => {
    const c = document.createElement('canvas');
    c.width = HW; c.height = HH;
    const ctx = c.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(img, 0, 0, HW, HH);
    try { heights = ctx.getImageData(0, 0, HW, HH).data; } catch (e) { return; }
    for (const m of tracked.values()) place(m);
    for (const m of nearby) place(m);
    for (const layer of Object.values(layers)) {
      for (const m of layer.dots) m.pos = surface(m.lat, m.lon);
      buildLine(layer);
    }
    if (popup) popup.pos = surface(popup.lat, popup.lon);
    dirty = true;
  };
  img.src = TOPO_URL;
})();

lookFrom(33.64, -84.43, 3.3);
targetDist = 3.3;
requestAnimationFrame(frame);

window.Globe3D = {
  setTracked, setNearby, clearNearby, showPopup, closePopup,
  setRoutes, setMateRoutes, flyTo, flyToRoute, getCenter, viewRadiusNm,
  onSelect(fn) { onSelect = fn; },
};
window.dispatchEvent(new Event('globe-ready'));
