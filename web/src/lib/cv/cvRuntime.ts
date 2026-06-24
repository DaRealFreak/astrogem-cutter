import cvModule from '@techstark/opencv-js';

let cvInstance: any = null;

export async function initOpenCv(): Promise<void> {
  if (cvInstance) return;
  const mod: any = cvModule;
  await new Promise<void>((resolve) => {
    // @techstark/opencv-js exposes a .then(cb) helper that fires cb(Module) once
    // the WASM runtime is initialized (immediately if already done, otherwise on
    // onRuntimeInitialized). We wrap it in a real Promise so we can await it.
    mod.then((instance: any) => {
      cvInstance = instance;
      resolve();
    });
  });
}

export function getCv(): any {
  if (!cvInstance) throw new Error('OpenCV not initialized. Call initOpenCv() first.');
  return cvInstance;
}
