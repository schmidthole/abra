import { CONFIG_DIR_NAME, type ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { install } from '../../../extensions/linear/pi.mjs';

export default function (pi: ExtensionAPI) {
  install(pi, CONFIG_DIR_NAME);
}
