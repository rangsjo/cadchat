// Decode the base64 little-endian mesh arrays that cadview.publish_kinematic writes (v64: float32 xyz, t64: uint32 indices).
function bytes(b64) {
  if (!b64) return new Uint8Array(0);
  const bin = atob(b64), out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export function decodeMesh(v64, t64) {
  const v = bytes(v64), t = bytes(t64);
  return { positions: new Float32Array(v.buffer, 0, v.length >> 2), index: new Uint32Array(t.buffer, 0, t.length >> 2) };
}
