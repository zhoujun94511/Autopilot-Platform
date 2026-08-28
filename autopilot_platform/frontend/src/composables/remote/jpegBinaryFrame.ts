/** APJF v1：与 runner `frame_bus.pack_binary_frame` 对齐。 */

const HEADER_SIZE = 10;
const MAGIC0 = 0x41; // A
const MAGIC1 = 0x50; // P
const MAGIC2 = 0x4a; // J
const MAGIC3 = 0x46; // F

export type UnpackedJpegFrame = {
  width: number;
  height: number;
  mime: string;
  bytes: Uint8Array;
};

export function unpackBinaryFrame(buf: ArrayBuffer): UnpackedJpegFrame | null {
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
  const mime = u8[5] === 1 ? "image/png" : "image/jpeg";
  const width = (u8[6] << 8) | u8[7];
  const height = (u8[8] << 8) | u8[9];
  return { width, height, mime, bytes: u8.subarray(HEADER_SIZE) };
}

export function jpegB64ToBytes(b64: string): Uint8Array {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}
