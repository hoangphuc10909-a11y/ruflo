// AI LIVE VOCAL — cầu nối MIDI Remote cho Cubase 12+ (đã viết cho Cubase Pro 15).
// Cài đặt: ứng dụng tự chép file này tới
//   %USERPROFILE%\Documents\Steinberg\Cubase\MIDI Remote\Driver Scripts\Local\ailive\vocalbridge\ailive_vocalbridge.js
// Cần 2 cổng MIDI ảo (loopMIDI): "AILive To Cubase" và "AILive From Cubase".
//
// Giao thức (ứng dụng <-> Cubase):
//   App -> Cubase: CC kênh 1. CC20-27 = Quick Control 1-8 của track đang chọn,
//                  CC28 = fader track đang chọn, CC29-32 = mức Send 1-4.
//                  CC118 = xin gửi lại toàn bộ trạng thái, CC119 = ping (giá trị luân phiên 0/127).
//                  (Dự phòng: SysEx F0 7D 41 4C 01 F7 = xin trạng thái; 02 = ping.)
//   Cubase -> App: SysEx F0 7D 41 4C <loại> <chỉ số> <dữ liệu> F7
//                  0x10 giá trị (14 bit), 0x11 chuỗi hiển thị, 0x12 tên (object|value),
//                  0x20 pong, 0x21 phiên bản script.
// Script không đổi gì trong Cubase nếu không nhận CC — mất kết nối không gây nhảy âm lượng.

var midiremote_api = require('midiremote_api_v1')

var SCRIPT_VERSION = 4
var deviceDriver = midiremote_api.makeDeviceDriver('ailive', 'vocalbridge', 'AI LIVE VOCAL')

var midiInput = deviceDriver.mPorts.makeMidiInput()
var midiOutput = deviceDriver.mPorts.makeMidiOutput()

deviceDriver.makeDetectionUnit().detectPortPair(midiInput, midiOutput)
    .expectInputNameEquals('AILive To Cubase')
    .expectOutputNameEquals('AILive From Cubase')

var surface = deviceDriver.mSurface
var HEADER = [0xF0, 0x7D, 0x41, 0x4C]
var N = 13
var knobs = []
var cache = []   // bộ nhớ trạng thái để trả lời khi ứng dụng xin "dump"

function encodeString(s) {
    // mỗi ký tự UTF-16 -> 3 byte 7 bit (an toàn cho SysEx, giữ được tiếng Việt)
    var out = []
    var str = String(s === undefined || s === null ? '' : s)
    for (var i = 0; i < str.length && i < 60; i++) {
        var c = str.charCodeAt(i)
        out.push((c >> 14) & 0x7F, (c >> 7) & 0x7F, c & 0x7F)
    }
    return out
}

function send(activeDevice, type, idx, payload) {
    var msg = HEADER.concat([type & 0x7F, idx & 0x7F]).concat(payload).concat([0xF7])
    midiOutput.sendMidi(activeDevice, msg)
}

function sendValue(activeDevice, idx, v) {
    var n = Math.max(0, Math.min(16383, Math.round(v * 16383)))
    send(activeDevice, 0x10, idx, [(n >> 7) & 0x7F, n & 0x7F])
}

function sendTitle(activeDevice, idx, objectTitle, valueTitle) {
    send(activeDevice, 0x12, idx, encodeString(objectTitle).concat([0x7F, 0x7F, 0x7F]).concat(encodeString(valueTitle)))
}

for (var i = 0; i < N; i++) {
    cache.push({ value: -1, display: '', obj: '', title: '' })
    var knob = surface.makeKnob(i * 2, 0, 2, 2)
    knob.mSurfaceValue.mMidiBinding.setInputPort(midiInput).bindToControlChange(0, 20 + i)
    ;(function (idx, k) {
        k.mSurfaceValue.mOnProcessValueChange = function (activeDevice, value) {
            cache[idx].value = value
            sendValue(activeDevice, idx, value)
        }
        k.mSurfaceValue.mOnDisplayValueChange = function (activeDevice, value, units) {
            var text = String(value) + (units ? ' ' + units : '')
            cache[idx].display = text
            send(activeDevice, 0x11, idx, encodeString(text))
        }
        k.mSurfaceValue.mOnTitleChange = function (activeDevice, objectTitle, valueTitle) {
            cache[idx].obj = objectTitle
            cache[idx].title = valueTitle
            sendTitle(activeDevice, idx, objectTitle, valueTitle)
        }
    })(i, knob)
    knobs.push(knob)
}

function pong(activeDevice) {
    send(activeDevice, 0x20, 0, [SCRIPT_VERSION & 0x7F])
}

function dump(activeDevice) {
    send(activeDevice, 0x21, 0, [SCRIPT_VERSION & 0x7F])
    for (var j = 0; j < N; j++) {
        sendTitle(activeDevice, j, cache[j].obj, cache[j].title)
        if (cache[j].value >= 0) sendValue(activeDevice, j, cache[j].value)
        send(activeDevice, 0x11, j, encodeString(cache[j].display))
    }
}

// Lệnh qua CC (chỉ dùng API đã có trong script mẫu của Steinberg): mỗi lần giá trị đổi = một lệnh
var dumpKnob = surface.makeKnob(0, 3, 1, 1)
dumpKnob.mSurfaceValue.mMidiBinding.setInputPort(midiInput).bindToControlChange(0, 118)
dumpKnob.mSurfaceValue.mOnProcessValueChange = function (activeDevice) { dump(activeDevice) }
var pingKnob = surface.makeKnob(1, 3, 1, 1)
pingKnob.mSurfaceValue.mMidiBinding.setInputPort(midiInput).bindToControlChange(0, 119)
pingKnob.mSurfaceValue.mOnProcessValueChange = function (activeDevice) { pong(activeDevice) }

// Dự phòng qua SysEx (nếu phiên bản Cubase hỗ trợ nhận SysEx trong script)
midiInput.mOnSysex = function (activeDevice, message) {
    if (message.length < 6 || message[1] !== 0x7D || message[2] !== 0x41 || message[3] !== 0x4C) return
    if (message[4] === 0x02) pong(activeDevice)
    else if (message[4] === 0x01) dump(activeDevice)
}

deviceDriver.mOnActivate = function (activeDevice) {
    send(activeDevice, 0x21, 0, [SCRIPT_VERSION & 0x7F])
}

var page = deviceDriver.mMapping.makePage('AI Live')
var channel = page.mHostAccess.mTrackSelection.mMixerChannel

// Tạo binding 2 lần: cách khắc phục đã biết để mOnTitleChange tiếp tục chạy trên Cubase >= 12.0.60
// (https://forums.steinberg.net/t/842187)
for (var pass = 0; pass < 2; pass++) {
    for (var q = 0; q < 8; q++) {
        page.makeValueBinding(knobs[q].mSurfaceValue, channel.mQuickControls.getByIndex(q)).setValueTakeOverModeJump()
    }
    page.makeValueBinding(knobs[8].mSurfaceValue, channel.mValue.mVolume).setValueTakeOverModeJump()
    for (var s = 0; s < 4; s++) {
        page.makeValueBinding(knobs[9 + s].mSurfaceValue, channel.mSends.getByIndex(s).mLevel).setValueTakeOverModeJump()
    }
}
