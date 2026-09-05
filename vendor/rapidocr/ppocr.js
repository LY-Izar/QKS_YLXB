(function(global){
'use strict';

var BASE = 'vendor/rapidocr/';
var DET_URL = BASE + 'models/ch_PP-OCRv4_det_infer.onnx';
var REC_URL = BASE + 'models/ch_PP-OCRv4_rec_infer.onnx';
var DICT_URL = BASE + 'models/ppocr_keys_v1.txt';

var _dict = null;
var _det = null;
var _rec = null;
var _ready = false;
var _initPromise = null;

function _abs(p){ return new URL(p, location.href).href; }

function _report(cb, stage, progress){
  try{ if(cb) cb({ stage: stage, progress: progress }); }catch(_){}
}

async function init(onProgress){
  if(_ready) return;
  if(_initPromise){ await _initPromise; return; }
  _initPromise = (async () => {
    if(typeof ort === 'undefined') throw new Error('onnxruntime not loaded');
    try{ ort.env.wasm.numThreads = 1; }catch(_){}
    try{ ort.env.wasm.wasmPaths = _abs(BASE); }catch(_){}
    _report(onProgress, '加载识别字典', 0.02);
    if(!_dict){
      const r = await fetch(_abs(DICT_URL));
      if(!r.ok) throw new Error('dict load failed');
      const txt = await r.text();
      const arr = txt.split('\n');
      while(arr.length && arr[arr.length - 1].replace(/\r$/, '') === '') arr.pop();
      const dict = [''];
      for(let i = 0; i < arr.length; i++) dict.push(arr[i].replace(/\r$/, ''));
      dict.push(' ');
      _dict = dict;
    }
    if(!_det){
      _report(onProgress, '加载检测模型', 0.06);
      _det = await ort.InferenceSession.create(_abs(DET_URL));
    }
    _report(onProgress, '检测模型就绪', 0.42);
    if(!_rec){
      _report(onProgress, '加载识别模型', 0.46);
      _rec = await ort.InferenceSession.create(_abs(REC_URL));
    }
    _report(onProgress, '模型就绪', 0.95);
    _ready = true;
  })();
  try{
    await _initPromise;
  }finally{
    _initPromise = null;
  }
}

function _loadImage(blob){
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(blob);
    img.onload = () => {
      try{
        const w = img.naturalWidth || img.width;
        const h = img.naturalHeight || img.height;
        const cv = document.createElement('canvas');
        cv.width = w; cv.height = h;
        const ctx = cv.getContext('2d', { willReadFrequently: true });
        ctx.drawImage(img, 0, 0, w, h);
        URL.revokeObjectURL(url);
        resolve({ canvas: cv, w: w, h: h });
      }catch(e){ URL.revokeObjectURL(url); reject(e); }
    };
    img.onerror = e => { URL.revokeObjectURL(url); reject(e); };
    img.src = url;
  });
}

function _detPreprocess(src){
  const w = src.w, h = src.h;
  let ratio = 1;
  const maxSide = Math.max(w, h);
  if(maxSide > 960) ratio = 960 / maxSide;
  const rw = Math.max(32, Math.round(w * ratio / 32) * 32);
  const rh = Math.max(32, Math.round(h * ratio / 32) * 32);
  const cv = document.createElement('canvas');
  cv.width = rw; cv.height = rh;
  const ctx = cv.getContext('2d', { willReadFrequently: true });
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(src.canvas, 0, 0, rw, rh);
  const d = ctx.getImageData(0, 0, rw, rh).data;
  const n = rw * rh;
  const f = new Float32Array(3 * n);
  const MEAN = [0.485, 0.456, 0.406], STD = [0.229, 0.224, 0.225];
  for(let i = 0, p = 0; i < d.length; i += 4, p++){
    f[p] = (d[i] / 255 - MEAN[0]) / STD[0];
    f[n + p] = (d[i + 1] / 255 - MEAN[1]) / STD[1];
    f[2 * n + p] = (d[i + 2] / 255 - MEAN[2]) / STD[2];
  }
  return { data: f, w: rw, h: rh };
}

function _dbPostprocess(prob, mapW, mapH, srcW, srcH){
  const TH = 0.3, UNCLIP = 1.5, SCORE_TH = 0.5;
  const visited = new Uint8Array(mapW * mapH);
  const stack = new Int32Array(mapW * mapH);
  const boxes = [];
  const ratioW = srcW / mapW, ratioH = srcH / mapH;
  for(let y = 0; y < mapH; y++){
    for(let x = 0; x < mapW; x++){
      const start = y * mapW + x;
      if(visited[start] || prob[start] <= TH) continue;
      let top = 0;
      stack[top++] = start;
      visited[start] = 1;
      let minX = x, maxX = x, minY = y, maxY = y, sum = 0, cnt = 0;
      while(top > 0){
        const cur = stack[--top];
        const cy = (cur / mapW) | 0;
        const cx = cur - cy * mapW;
        sum += prob[cur]; cnt++;
        if(cx < minX) minX = cx;
        if(cx > maxX) maxX = cx;
        if(cy < minY) minY = cy;
        if(cy > maxY) maxY = cy;
        if(cx > 0){ const n = cur - 1; if(!visited[n] && prob[n] > TH){ visited[n] = 1; stack[top++] = n; } }
        if(cx < mapW - 1){ const n = cur + 1; if(!visited[n] && prob[n] > TH){ visited[n] = 1; stack[top++] = n; } }
        if(cy > 0){ const n = cur - mapW; if(!visited[n] && prob[n] > TH){ visited[n] = 1; stack[top++] = n; } }
        if(cy < mapH - 1){ const n = cur + mapW; if(!visited[n] && prob[n] > TH){ visited[n] = 1; stack[top++] = n; } }
      }
      const bw = maxX - minX + 1, bh = maxY - minY + 1;
      if(bw < 3 || bh < 3 || cnt < 6) continue;
      const score = sum / cnt;
      if(score < SCORE_TH) continue;
      const offset = bw * bh * UNCLIP / (2 * (bw + bh));
      let x0 = (minX - offset) * ratioW, x1 = (maxX + 1 + offset) * ratioW;
      let y0 = (minY - offset) * ratioH, y1 = (maxY + 1 + offset) * ratioH;
      if(x0 < 0) x0 = 0;
      if(y0 < 0) y0 = 0;
      if(x1 > srcW) x1 = srcW;
      if(y1 > srcH) y1 = srcH;
      boxes.push({ x0: x0, y0: y0, x1: x1, y1: y1, score: score });
    }
  }
  return boxes;
}

function _sortLines(boxes){
  const sorted = boxes.slice().sort((a, b) => ((a.y0 + a.y1) - (b.y0 + b.y1)));
  const rows = [];
  for(let i = 0; i < sorted.length; i++){
    const b = sorted[i];
    const cy = (b.y0 + b.y1) / 2, h = b.y1 - b.y0;
    let row = null;
    for(let j = 0; j < rows.length; j++){
      if(Math.abs(cy - rows[j].cy) < Math.max(h, rows[j].h) * 0.5){ row = rows[j]; break; }
    }
    if(row){
      row.boxes.push(b);
      row.cy = (row.cy * (row.boxes.length - 1) + cy) / row.boxes.length;
      row.h = Math.max(row.h, h);
    }else{
      rows.push({ cy: cy, h: h, boxes: [b] });
    }
  }
  rows.sort((a, b) => a.cy - b.cy);
  const lines = [];
  for(let i = 0; i < rows.length; i++){
    rows[i].boxes.sort((a, b) => a.x0 - b.x0);
    lines.push(rows[i].boxes);
  }
  return lines;
}

function _ctcDecode(data, T, C){
  let text = '', sum = 0, cnt = 0, last = -1;
  for(let t = 0; t < T; t++){
    const base = t * C;
    let mi = 0, mv = data[base];
    for(let c = 1; c < C; c++){
      const v = data[base + c];
      if(v > mv){ mv = v; mi = c; }
    }
    if(mi !== 0){
      if(mi !== last && _dict[mi]) text += _dict[mi];
      sum += mv; cnt++;
    }
    last = mi;
  }
  return { text: text, score: cnt ? sum / cnt : 0 };
}

async function _recognizeLine(src, box){
  let x0 = Math.max(0, Math.floor(box.x0)), y0 = Math.max(0, Math.floor(box.y0));
  let x1 = Math.min(src.w, Math.ceil(box.x1)), y1 = Math.min(src.h, Math.ceil(box.y1));
  const cw = x1 - x0, chh = y1 - y0;
  if(cw < 2 || chh < 2) return null;
  const TH = 48;
  let tw = Math.round(cw * TH / chh);
  if(tw > 320) tw = 320;
  if(tw < 16) tw = 16;
  const cv = document.createElement('canvas');
  cv.width = tw; cv.height = TH;
  const ctx = cv.getContext('2d', { willReadFrequently: true });
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(src.canvas, x0, y0, cw, chh, 0, 0, tw, TH);
  const d = ctx.getImageData(0, 0, tw, TH).data;
  const n = tw * TH;
  const f = new Float32Array(3 * n);
  for(let i = 0, p = 0; i < d.length; i += 4, p++){
    f[p] = (d[i] / 255 - 0.5) / 0.5;
    f[n + p] = (d[i + 1] / 255 - 0.5) / 0.5;
    f[2 * n + p] = (d[i + 2] / 255 - 0.5) / 0.5;
  }
  const feeds = {};
  feeds[_rec.inputNames[0]] = new ort.Tensor('float32', f, [1, 3, TH, tw]);
  const out = await _rec.run(feeds);
  const t = out[_rec.outputNames[0]];
  return _ctcDecode(t.data, t.dims[1], t.dims[2]);
}

async function recognize(blob, onProgress){
  await init(onProgress);
  const src = await _loadImage(blob);
  _report(onProgress, '文本检测中', 0.1);
  const pre = _detPreprocess(src);
  const feeds = {};
  feeds[_det.inputNames[0]] = new ort.Tensor('float32', pre.data, [1, 3, pre.h, pre.w]);
  const detOut = await _det.run(feeds);
  const dt = detOut[_det.outputNames[0]];
  const mapH = dt.dims[2], mapW = dt.dims[3];
  const boxes = _dbPostprocess(dt.data, mapW, mapH, src.w, src.h);
  const rows = _sortLines(boxes);
  _report(onProgress, '文本识别中', 0.3);
  const results = [];
  for(let i = 0; i < rows.length; i++){
    let rowText = '';
    let prev = null;
    for(let j = 0; j < rows[i].length; j++){
      const b = rows[i][j];
      const r = await _recognizeLine(src, b);
      if(r && r.text){
        if(prev && (b.x0 - prev.x1) > (prev.y1 - prev.y0) * 0.6) rowText += ' ';
        rowText += r.text;
        prev = b;
      }
    }
    if(rowText) results.push(rowText);
    _report(onProgress, '文本识别中', 0.3 + 0.68 * (i + 1) / Math.max(1, rows.length));
  }
  _report(onProgress, '识别完成', 1);
  return { text: results.join('\n'), lines: results };
}

global.RapidOCR = {
  init: init,
  recognize: recognize,
  isReady: function(){ return _ready; }
};

})(typeof window !== 'undefined' ? window : this);
