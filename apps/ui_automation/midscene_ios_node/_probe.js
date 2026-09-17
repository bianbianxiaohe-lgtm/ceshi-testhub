// 临时探针：打印 @midscene/ios 的导出与方法名（排障用，可删）
const m = require('@midscene/ios');
console.log('exports:', Object.keys(m).join(','));
const { IOSAgent, IOSDevice } = m;
const protoNames = (cls) => {
  let out = new Set();
  let p = cls && cls.prototype;
  while (p && p !== Object.prototype) {
    Object.getOwnPropertyNames(p).forEach((n) => out.add(n));
    p = Object.getPrototypeOf(p);
  }
  return [...out].join(',');
};
if (IOSAgent) console.log('agent:', protoNames(IOSAgent));
if (IOSDevice) console.log('device:', protoNames(IOSDevice));
