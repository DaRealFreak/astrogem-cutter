import { readFileSync } from 'node:fs';
import { extname } from 'node:path';
import jpeg from 'jpeg-js';
import { PNG } from 'pngjs';
import { getCv } from '../../src/lib/cv/cvRuntime';

// cv.imdecode is not available in the @techstark/opencv-js WASM build, so we
// decode images with pure-JS decoders (jpeg-js for JPEG, pngjs for PNG) and
// convert the resulting RGBA buffer into a BGR cv.Mat via matFromImageData +
// cvtColor (matching what cv2.imread produces in Python).

export function decodeToBgrMat(absPath: string): any {
  const cv = getCv();
  const buf = readFileSync(absPath);
  const ext = extname(absPath).toLowerCase();

  let width: number;
  let height: number;
  let rgbaData: Uint8Array;

  if (ext === '.jpg' || ext === '.jpeg') {
    const decoded = jpeg.decode(buf, { useTArray: true });
    width = decoded.width;
    height = decoded.height;
    rgbaData = decoded.data as Uint8Array;
  } else if (ext === '.png') {
    const png = PNG.sync.read(buf);
    width = png.width;
    height = png.height;
    rgbaData = png.data as unknown as Uint8Array;
  } else {
    throw new Error(`decodeToBgrMat: unsupported extension "${ext}" (${absPath})`);
  }

  // Build an RGBA Mat and convert to BGR (3-channel, like cv2.imread)
  const rgba = cv.matFromImageData({ data: rgbaData, width, height });
  const bgr = new cv.Mat();
  cv.cvtColor(rgba, bgr, cv.COLOR_RGBA2BGR);
  rgba.delete();
  return bgr;
}
