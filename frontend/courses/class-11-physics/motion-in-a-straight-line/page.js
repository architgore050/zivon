function patchDiagrams(){
  if(typeof document==='undefined')return;
  var svgs=document.querySelectorAll('svg');
  for(var i=0;i<svgs.length;i++){
    var svg=svgs[i];
    var txt=svg.textContent||'';
    if(txt.indexOf('tangent slope')!==-1){
      svg.setAttribute('role','img');
      svg.setAttribute('aria-label','Position-time graph: horizontal axis t, vertical axis x, a curve with point P, and a tangent line at P labelled tangent slope = v');
    } else if(txt.indexOf('area = displacement')!==-1){
      svg.setAttribute('role','img');
      svg.setAttribute('aria-label','Velocity-time graph: horizontal axis t, vertical axis v, a straight line labelled slope = a, and a dashed trapezoid under the line down to the t-axis labelled area = displacement');
      var rects=svg.querySelectorAll('rect');
      for(var j=0;j<rects.length;j++){
        var r=rects[j];
        if(r.getAttribute('stroke-dasharray')){
          var NS=svg.namespaceURI||'svg';
          var poly=document.createElementNS(NS,'polygon');
          poly.setAttribute('points','60,150 340,60 340,190 60,190');
          poly.setAttribute('fill','none');
          poly.setAttribute('stroke','#1F3A9E');
          poly.setAttribute('stroke-width','2');
          poly.setAttribute('stroke-dasharray','4 4');
          r.parentNode.replaceChild(poly,r);
        }
      }
    }
  }
}
function isLangBar(el){return el&&(el.classList&&(el.classList.contains('zn-lang-bar')||el.classList.contains('bar'))||el.getAttribute&&el.getAttribute('data-lang-bar')==='1');}
function dedupePageChrome(){
  try{
    var headers=document.querySelectorAll('header');
    var keptHeader=false;
    for(var i=0;i<headers.length;i++){if(isLangBar(headers[i]))continue; if(!keptHeader){keptHeader=true;}else{headers[i].remove();}}
    var footers=document.querySelectorAll('footer');
    for(var j=1;j<footers.length;j++){footers[j].remove();}
    var h1s=document.querySelectorAll('h1');
    for(var k=1;k<h1s.length;k++){h1s[k].remove();}
    var seen={};
    var candidates=document.querySelectorAll('dl,section,div,ul,aside');
    for(var m=0;m<candidates.length;m++){
      var el=candidates[m];
      if(isLangBar(el)||el.closest&&el.closest('.zn-lang-bar,.bar'))continue;
      var cls=String(el.className||'');
      var t=(el.textContent||'').replace(/\s+/g,' ').trim();
      var low=t.toLowerCase();
      var isGloss=cls.indexOf('gloss')!==-1||low.indexOf('glossary')!==-1||low.indexOf('words to keep')!==-1;
      if(isGloss&&t.length>20){
        var key='gloss:'+low.slice(0,120);
        if(seen[key]){el.remove();}else{seen[key]=el;}
      } else if(t.length>80){
        var key2=el.tagName+':'+low.slice(0,160);
        if(seen[key2]&&(el.tagName==='DL'||el.tagName==='SECTION'||el.tagName==='FOOTER'||el.tagName==='HEADER')){el.remove();}else if(!seen[key2]){seen[key2]=el;}
      }
    }
    var glossEls=document.querySelectorAll('.gloss,[class*="gloss"]');
    for(var n=1;n<glossEls.length;n++){glossEls[n].remove();}
  }catch(e){}
}
function ensureLanguageBar(){
  try{
    var existing=document.querySelector('.zn-lang-bar');
    if(existing)return;
    var bar=document.createElement('header');
    bar.className='zn-lang-bar bar';
    bar.setAttribute('data-lang-bar','1');
    bar.innerHTML='<div class="zn-lang-in in"><span class="zn-lang-lab lab">Language</span><div class="zn-lang-row row" role="radiogroup" aria-label="Language">'+['English','हिन्दी','Hinglish'].map(function(l,idx){return '<button type="button" class="zn-chip chip" role="radio" aria-checked="'+(idx===0?'true':'false')+'">'+l+'</button>';}).join('')+'</div></div>';
    document.body.insertBefore(bar,document.body.firstChild);
    var chips=bar.querySelectorAll('.zn-chip');
    for(var i=0;i<chips.length;i++){
      chips[i].addEventListener('click',function(){
        for(var j=0;j<chips.length;j++){chips[j].setAttribute('aria-checked',chips[j]===this?'true':'false');}
      });
    }
  }catch(e){}
}
if(typeof document!=='undefined'){
  patchDiagrams(); dedupePageChrome(); ensureLanguageBar();
  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',function(){patchDiagrams();dedupePageChrome();ensureLanguageBar();});}
  if(typeof MutationObserver!=='undefined'&&document.body){
    var mo=new MutationObserver(function(){patchDiagrams();});
    mo.observe(document.body,{childList:true,subtree:true});
  }
  setTimeout(function(){patchDiagrams();dedupePageChrome();ensureLanguageBar();},0);
}
function updateSimReadout(ctx,muzzle,bulletGround,bulletRelCar,van,car){
  var text='Muzzle speed '+muzzle.toFixed(0)+' m/s. Van '+van.toFixed(1)+' m/s, thief car '+car.toFixed(1)+' m/s. Bullet speed relative to ground '+bulletGround.toFixed(1)+' m/s. Bullet speed relative to thief car '+bulletRelCar.toFixed(1)+' m/s.';
  try{if(ctx&&ctx.g&&ctx.g.canvas){ctx.g.canvas.setAttribute('role','img');ctx.g.canvas.setAttribute('aria-label',text);}}catch(e){}
  try{
    var container=document.querySelector('.zn-sim-b-26');
    if(!container)return;
    var read=container.querySelector('.sim-read');
    if(!read){read=document.createElement('div');read.className='sim-read';read.setAttribute('aria-live','polite');read.setAttribute('role','status');container.appendChild(read);}
    read.textContent=text;
  }catch(e){}
}
ZivonSim.register("b-26", {
  init: function (ctx) { ctx.state = {}; },
  draw: function (ctx) {
    var g = ctx.g;
    var W = 480, H = 320;
    var muzzle = (ctx.values && typeof ctx.values.muzzle === "number") ? ctx.values.muzzle : 150;
    var van = 30 * 1000 / 3600;
    var car = 192 * 1000 / 3600;
    var bulletGround = van + muzzle;
    var bulletRelCar = bulletGround - car;
    updateSimReadout(ctx,muzzle,bulletGround,bulletRelCar,van,car);
    var ink = "#1C1B18", graphite = "#5A5748", blue = "#1F3A9E", paperLight = "#F6F0CF";
    function safeText(text,x,y){var w=g.measureText(text).width; x=Math.max(8,Math.min(x,W-w-8)); g.fillText(text,x,y); return x;}
    function arrow(x, y, len, color, width) {
      var x2 = Math.min(464, x + len);
      g.strokeStyle = color; g.fillStyle = color; g.lineWidth = width || 3; g.lineCap = "round"; g.lineJoin = "round";
      g.beginPath(); g.moveTo(x, y); g.lineTo(x2, y); g.stroke();
      g.beginPath(); g.moveTo(x2, y); g.lineTo(x2 - 10, y - 5); g.lineTo(x2 - 10, y + 5); g.closePath(); g.fill();
    }
    function rr(x, y, w, h, r) {
      g.beginPath();
      g.moveTo(x + r, y); g.lineTo(x + w - r, y); g.arcTo(x + w, y, x + w, y + r, r);
      g.lineTo(x + w, y + h - r); g.arcTo(x + w, y + h, x + w - r, y + h, r);
      g.lineTo(x + r, y + h); g.arcTo(x, y + h, x, y + h - r, r);
      g.lineTo(x, y + r); g.arcTo(x, y, x + r, y, r); g.closePath();
    }
    function vehicle(x, y, w, h, isVan) {
      x = Math.max(8,Math.min(x, W - w - 8));
      g.strokeStyle = ink; g.fillStyle = paperLight; g.lineWidth = 2.6;
      rr(x, y, w, h, 2); g.fill(); g.stroke();
      if (isVan) {
        g.beginPath(); g.moveTo(x + w - 18, y); g.lineTo(x + w - 18, y + h); g.stroke();
        g.beginPath(); g.moveTo(x + w - 18, y + 8); g.lineTo(x + w - 4, y + 8); g.lineTo(x + w - 4, y + h); g.stroke();
      } else {
        g.beginPath(); g.moveTo(x + 14, y); g.lineTo(x + 22, y - 12); g.lineTo(x + w - 20, y - 12); g.lineTo(x + w - 12, y); g.stroke();
      }
      g.fillStyle = ink;
      g.beginPath(); g.arc(x + 14, y + h, 6, 0, Math.PI * 2); g.fill();
      g.beginPath(); g.arc(x + w - 14, y + h, 6, 0, Math.PI * 2); g.fill();
      return x;
    }
    g.fillStyle = paperLight; g.fillRect(0, 0, W, H);
    g.textBaseline = "alphabetic";
    g.font = "700 14px 'Courier Prime', 'Courier New', monospace";
    g.fillStyle = graphite;
    safeText("speeds, same direction ->",16,22);
    var rows = [["van", van, ink],["car", car, ink],["bullet / ground", bulletGround, blue]];
    var maxSpeed = Math.max(van, car, bulletGround);
    var scale = Math.min(1.1, 200 / maxSpeed);
    for (var i = 0; i < rows.length; i++) {
      var y = 42 + i * 24;
      g.fillStyle = ink; safeText(rows[i][0],16,y+5);
      var len = rows[i][1] * scale;
      arrow(150, y, len, rows[i][2], 3);
      g.fillStyle = rows[i][2];
      safeText(rows[i][1].toFixed(1) + " m/s", 150 + len + 14, y + 5);
    }
    g.strokeStyle = graphite; g.lineWidth = 1.5; g.setLineDash([4, 5]);
    g.beginPath(); g.moveTo(16, 118); g.lineTo(464, 118); g.stroke(); g.setLineDash([]);
    var T = 5, tt = ctx.t % T, k = 0.32;
    var vanX = Math.min(36 + van * k * tt, W-64-8);
    var carX = Math.min(260 + car * k * tt, W-70-8);
    var bulletX = Math.min(70 + bulletGround * k * tt, 460);
    var roadY = 252;
    g.strokeStyle = ink; g.lineWidth = 3; g.lineCap = "round";
    g.beginPath(); g.moveTo(16, roadY); g.lineTo(464, roadY); g.stroke();
    g.strokeStyle = graphite; g.lineWidth = 1.5;
    for (var j = 0; j < 10; j++) {var tx = 36 + j * 44; g.beginPath(); g.moveTo(tx, roadY + 10); g.lineTo(tx - 8, roadY); g.stroke();}
    vanX = vehicle(vanX, 198, 64, 38, true);
    carX = vehicle(carX, 206, 70, 32, false);
    g.fillStyle = ink; g.font = "700 14px 'Courier Prime', 'Courier New', monospace";
    safeText("police van",vanX,192);
    safeText("thief car",carX,200);
    if (bulletX > 10 && bulletX < 470) {
      g.strokeStyle = graphite; g.lineWidth = 2; g.setLineDash([4, 5]);
      g.beginPath(); g.moveTo(Math.max(16, bulletX - 42), 222); g.lineTo(bulletX - 6, 222); g.stroke(); g.setLineDash([]);
      g.fillStyle = blue; g.beginPath(); g.arc(bulletX, 222, 6, 0, Math.PI * 2); g.fill();
      g.fillStyle = blue; safeText("bullet",Math.max(16, bulletX - 18),214);
    }
    if (bulletX >= carX && bulletX <= carX + 70) {
      g.strokeStyle = blue; g.lineWidth = 3;
      g.beginPath(); g.arc(carX + 35, 222, 30, 0, Math.PI * 2); g.stroke();
      g.fillStyle = blue; safeText("bullet reaches car",300,150);
    }
    arrow(vanX + 4, 176, van * scale, ink, 3);
    arrow(carX + 4, 184, car * scale, ink, 3);
    g.font = "700 15px 'Courier Prime', 'Courier New', monospace";
    g.fillStyle = ink;
    safeText("bullet / ground = 8.3 + " + muzzle.toFixed(0) + " = " + bulletGround.toFixed(1) + " m/s",16,284);
    g.fillStyle = blue;
    safeText("bullet / car = " + bulletGround.toFixed(1) + " - 53.3 = " + bulletRelCar.toFixed(1) + " m/s",16,308);
  }
});
