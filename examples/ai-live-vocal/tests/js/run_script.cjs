// Chạy ailive_vocalbridge.js với API MIDI Remote giả lập; in ra SysEx dạng JSON.
const path = require('path');
const sent = [];
const knobs = [];
let sysexHandler = null, activateHandler = null;
const bindings = [];
function hostValue(name) { return { name }; }
const channel = {
  mQuickControls: { getByIndex: i => hostValue('QC' + (i + 1)) },
  mValue: { mVolume: hostValue('Volume') },
  mSends: { getByIndex: i => ({ mLevel: hostValue('Send' + (i + 1)) }) },
};
const api = {
  makeDeviceDriver: (v, d, a) => {
    const drv = {
      mPorts: {
        makeMidiInput: () => ({ set mOnSysex(f) { sysexHandler = f; } }),
        makeMidiOutput: () => ({ sendMidi: (dev, bytes) => sent.push(bytes) }),
      },
      makeDetectionUnit: () => ({ detectPortPair: () => ({ expectInputNameEquals() { return this; }, expectOutputNameEquals() { return this; } }) }),
      mSurface: {
        makeKnob: () => {
          const sv = { mMidiBinding: { setInputPort() { return { bindToControlChange: (ch, cc) => { sv.cc = cc; } }; } } };
          const k = { mSurfaceValue: sv }; knobs.push(k); return k;
        },
      },
      mMapping: { makePage: () => ({
        mHostAccess: { mTrackSelection: { mMixerChannel: channel } },
        makeValueBinding: (sv, hv) => { bindings.push([sv.cc, hv.name]); return { setValueTakeOverModeJump() { return this; } }; },
      }) },
    };
    Object.defineProperty(drv, 'mOnActivate', { set(f) { activateHandler = f; } });
    return drv;
  },
};
// Nạp script như Cubase làm: chỉ có require('midiremote_api_v1'), cú pháp ES5
const src = require('fs').readFileSync(path.resolve(__dirname, '../../cubase/ailive_vocalbridge.js'), 'utf8');
new Function('require', src)(name => { if (name !== 'midiremote_api_v1') throw new Error(name); return api; });
const dev = {};
activateHandler(dev);
knobs[2].mSurfaceValue.mOnTitleChange(dev, 'Auto-Tune Artist', 'Retune Speed');
knobs[2].mSurfaceValue.mOnDisplayValueChange(dev, '25', '');
knobs[2].mSurfaceValue.mOnProcessValueChange(dev, 0.0625);
knobs[8].mSurfaceValue.mOnTitleChange(dev, 'Giọng Chính', 'Volume');
knobs[8].mSurfaceValue.mOnDisplayValueChange(dev, '-6.02', 'dB');
sysexHandler(dev, [0xF0, 0x7D, 0x41, 0x4C, 0x02, 0xF7]);
sysexHandler(dev, [0xF0, 0x7D, 0x41, 0x4C, 0x01, 0xF7]);
console.log(JSON.stringify({ sent, bindings, knobs: knobs.length }));
