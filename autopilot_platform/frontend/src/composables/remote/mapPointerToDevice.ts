/** 远控画面点击：把指针从黑边内的画面矩形换算到设备像素。 */

export type RectLike = {
  left: number;
  top: number;
  width: number;
  height: number;
};

export function letterboxRect(box: RectLike, contentWidth: number, contentHeight: number): RectLike {
  if (!contentWidth || !contentHeight || !box.width || !box.height) {
    return { left: box.left, top: box.top, width: box.width, height: box.height };
  }
  const boxAspect = box.width / box.height;
  const contentAspect = contentWidth / contentHeight;
  if (contentAspect > boxAspect) {
    const width = box.width;
    const height = box.width / contentAspect;
    return {
      left: box.left,
      top: box.top + (box.height - height) / 2,
      width,
      height,
    };
  }
  const height = box.height;
  const width = box.height * contentAspect;
  return {
    left: box.left + (box.width - width) / 2,
    top: box.top,
    width,
    height,
  };
}

export function mapPointerToDevice(
  clientX: number,
  clientY: number,
  surface: RectLike,
  deviceWidth: number,
  deviceHeight: number,
): { x: number; y: number } | null {
  if (!deviceWidth || !deviceHeight || !surface.width || !surface.height) return null;
  const x = Math.min(1, Math.max(0, (clientX - surface.left) / surface.width));
  const y = Math.min(1, Math.max(0, (clientY - surface.top) / surface.height));
  return { x: Math.round(x * deviceWidth), y: Math.round(y * deviceHeight) };
}
