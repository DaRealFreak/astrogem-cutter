import { getCv } from '../../src/lib/cv/cvRuntime';

// Browser-only: fetch an image URL, decode via canvas, return a grayscale cv.Mat.
export async function loadGrayMat(url: string): Promise<any> {
  const cv = getCv();
  const blob = await (await fetch(url)).blob();
  const bmp = await createImageBitmap(blob);
  const canvas = document.createElement('canvas');
  canvas.width = bmp.width;
  canvas.height = bmp.height;
  canvas.getContext('2d')!.drawImage(bmp, 0, 0);
  bmp.close();                               // release the decoded ImageBitmap (GPU memory)
  const rgba = cv.imread(canvas);            // 4-channel RGBA Mat
  const gray = new cv.Mat();
  cv.cvtColor(rgba, gray, cv.COLOR_RGBA2GRAY); // same luminance as cv2 BGR2GRAY
  rgba.delete();
  return gray;
}
