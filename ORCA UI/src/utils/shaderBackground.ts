export function initShaderBackground(containerId: string): void {
  const container = document.getElementById(containerId);
  if (!container) return;

  const canvas = document.createElement('canvas');
  canvas.id = 'orca-shader-canvas';
  canvas.style.position = 'fixed';
  canvas.style.inset = '0';
  canvas.style.width = '100%';
  canvas.style.height = '100%';
  canvas.style.zIndex = '-1';
  canvas.style.pointerEvents = 'none';
  canvas.style.opacity = '0.65';
  container.appendChild(canvas);

  function syncSize() {
    const w = window.innerWidth || 1280;
    const h = window.innerHeight || 720;
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
  }

  window.addEventListener('resize', syncSize);
  syncSize();

  const gl = (canvas.getContext('webgl') || canvas.getContext('experimental-webgl')) as WebGLRenderingContext | null;
  if (!gl) return;

  const vs = `
    attribute vec2 a_position;
    varying vec2 v_texCoord;
    void main() {
      v_texCoord = a_position * 0.5 + 0.5;
      gl_Position = vec4(a_position, 0.0, 1.0);
    }
  `;

  const fs = `
    precision highp float;
    uniform float u_time;
    uniform vec2 u_resolution;
    uniform vec2 u_mouse;
    varying vec2 v_texCoord;

    float hash(vec2 p) {
      p = fract(p * vec2(123.34, 456.21));
      p += dot(p, p + 45.32);
      return fract(p.x * p.y);
    }

    float line(vec2 p, vec2 a, vec2 b, float width) {
      vec2 pa = p - a, ba = b - a;
      float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
      return smoothstep(width, width * 0.5, length(pa - ba * h));
    }

    void main() {
      vec2 uv = v_texCoord;
      vec2 aspect = vec2(u_resolution.x / u_resolution.y, 1.0);
      vec2 p = uv * aspect;

      // Maritime Light Blue Surface (#f0f7fc)
      vec3 backgroundColor = vec3(0.941, 0.968, 0.988);
      // Ocean Sky Blue Particle & Line Color (#0284c7)
      vec3 accentColor = vec3(0.008, 0.518, 0.780);

      float particles = 0.0;
      float connections = 0.0;
      float gridSize = 8.5;
      vec2 gridId = floor(p * gridSize);
      vec2 gridUv = fract(p * gridSize) - 0.5;

      for(int y = -1; y <= 1; y++) {
        for(int x = -1; x <= 1; x++) {
          vec2 offset = vec2(float(x), float(y));
          vec2 currentGridId = gridId + offset;
          float h = hash(currentGridId);

          vec2 pos = offset + vec2(
            sin(u_time * 0.15 + h * 6.28) * 0.35,
            cos(u_time * 0.2 + h * 6.28) * 0.35
          );

          float dist = length(gridUv - pos);
          float size = 0.015 + h * 0.015;
          float particle = smoothstep(size, size * 0.5, dist);
          float opacity = 0.35 + 0.45 * h;
          particles += particle * opacity;

          vec2 nextOffset = vec2(1.0, 0.0);
          vec2 nextGridId = currentGridId + nextOffset;
          float nextH = hash(nextGridId);

          if (h > 0.42 && nextH > 0.42) {
            vec2 nextPos = nextOffset + offset + vec2(
              sin(u_time * 0.15 + nextH * 6.28) * 0.35,
              cos(u_time * 0.2 + nextH * 6.28) * 0.35
            );
            float l = line(gridUv, pos, nextPos, 0.0025);
            float lFade = smoothstep(1.5, 0.5, length(pos - nextPos));
            connections += l * lFade * 0.2;
          }
        }
      }

      float mask = smoothstep(0.25, 0.8, abs(uv.y - 0.5) + abs(uv.x - 0.5) * 0.5);
      float finalAlpha = clamp(particles + connections, 0.0, 1.0) * mask;
      vec3 color = mix(backgroundColor, accentColor, finalAlpha * 0.4);

      gl_FragColor = vec4(color, 1.0);
    }
  `;

  function cs(type: number, src: string): WebGLShader | null {
    if (!gl) return null;
    const s = gl.createShader(type);
    if (!s) return null;
    gl.shaderSource(s, src);
    gl.compileShader(s);
    return s;
  }

  const prog = gl.createProgram();
  if (!prog) return;

  const vsShader = cs(gl.VERTEX_SHADER, vs);
  const fsShader = cs(gl.FRAGMENT_SHADER, fs);
  if (!vsShader || !fsShader) return;

  gl.attachShader(prog, vsShader);
  gl.attachShader(prog, fsShader);
  gl.linkProgram(prog);
  gl.useProgram(prog);

  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, 1,1]), gl.STATIC_DRAW);

  const pos = gl.getAttribLocation(prog, 'a_position');
  gl.enableVertexAttribArray(pos);
  gl.vertexAttribPointer(pos, 2, gl.FLOAT, false, 0, 0);

  const uTime = gl.getUniformLocation(prog, 'u_time');
  const uRes = gl.getUniformLocation(prog, 'u_resolution');
  const uMouse = gl.getUniformLocation(prog, 'u_mouse');

  let mouse = { x: canvas.width / 2, y: canvas.height / 2 };
  window.addEventListener('mousemove', (event) => {
    mouse.x = event.clientX;
    mouse.y = event.clientY;
  });

  function render(t: number) {
    if (!gl) return;
    gl.viewport(0, 0, canvas.width, canvas.height);
    if (uTime) gl.uniform1f(uTime, t * 0.001);
    if (uRes) gl.uniform2f(uRes, canvas.width, canvas.height);
    if (uMouse) gl.uniform2f(uMouse, mouse.x, mouse.y);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    requestAnimationFrame(render);
  }
  requestAnimationFrame(render);
}
