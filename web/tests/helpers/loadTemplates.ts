import { groupBySet, TemplateStore } from '../../src/lib/cv/templates';
import { loadGrayMat } from './loadImage';

// vite enumerates the PNGs at build time; keys are the matched paths, values are served URLs.
const TEMPLATE_URLS = import.meta.glob(
  '../../../arkgrid/vision/templates/**/*.png',
  { eager: true, query: '?url', import: 'default' },
) as Record<string, string>;

export async function loadTemplateStore(): Promise<TemplateStore> {
  const entries: Array<[string, any]> = [];
  for (const [path, url] of Object.entries(TEMPLATE_URLS)) {
    const rel = path.split('/templates/')[1]!.replace(/\.png$/, ''); // "willpower/1", "side_nodes/names/foo"
    entries.push([rel, await loadGrayMat(url)]);
  }
  return new TemplateStore(groupBySet(entries));
}
