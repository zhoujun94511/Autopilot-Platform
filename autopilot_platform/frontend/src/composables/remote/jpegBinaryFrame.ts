/** APJF v1：与 runner `frame_bus.pack_binary_frame` 对齐。 */

const HEADER_SIZE = 10;
const MAGIC0 = 0x41; // A
const MAGIC1 = 0x50; // P
const MAGIC2 = 0x4a; // J
const MAGIC3 = 0x46; // F

export type UnpackedJpegFrame = {
  kind: "image";
  width: number;
  height: number;
  mime: string;
  bytes: Uint8Array;
};

export type UnpackedHevcFrame = {
  kind: "hevc-config" | "hevc";
  codec: string;
  description: Uint8Array;
  packet: Uint8Array;
};

export type UnpackedBinaryFrame = UnpackedJpegFrame | UnpackedHevcFrame;

export function unpackBinaryFrame(buf: ArrayBuffer): UnpackedBinaryFrame | null {
  if (buf.byteLength < HEADER_SIZE) return null;
  const u8 = new Uint8Array(buf);
  if (
    u8[0] !== MAGIC0 ||
    u8[1] !== MAGIC1 ||
    u8[2] !== MAGIC2 ||
    u8[3] !== MAGIC3 ||
    u8[4] !== 1
  ) {
    return null;
  }
  const payload = u8.subarray(HEADER_SIZE);
  if (u8[5] === 2) {
    const nul = payload.indexOf(0);
    if (nul <= 0) return null;
    const codec = new TextDecoder().decode(payload.subarray(0, nul));
    return {
      kind: "hevc-config",
      codec,
      description: payload.subarray(nul + 1),
      packet: payload,
    };
  }
  if (u8[5] === 3) {
    return {
      kind: "hevc",
      codec: "",
      description: new Uint8Array(),
      packet: payload,
    };
  }
  const mime = u8[5] === 1 ? "image/png" : "image/jpeg";
  const width = (u8[6] << 8) | u8[7];
  const height = (u8[8] << 8) | u8[9];
  return { kind: "image", width, height, mime, bytes: payload };
}

export function jpegB64ToBytes(b64: string): Uint8Array {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}
