/* 研究方向 04「实际完成曲线与游戏用户粘性」—— 直接内嵌刘宇翔的原始交付页。
 *
 * 原页是 5.3MB 的自包含单文件（CSS/JS/数据全内联，不依赖网络或后端），单独放进 iframe
 * 就能完整运行；21 张原图与 35 份来源明细按原相对路径一起发布，页内链接可以直接点开。
 *
 * 面板只负责给一个足够大的容器和「新标签页 / 全屏」两个出口，不重算、不改写原页内容。
 * 与 trends / clusters 保持同一形态：IIFE + window.RetentionResearch.mount(container)。
 */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const SRC = '/assets/research/lyx/WEB/index.html';
  let escBound = false;

  /** Esc 退出全屏。只绑一次：切走再切回会重新挂载，重复绑会攒监听器。 */
  function bindEscape() {
    if (escBound) return;
    escBound = true;
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      const root = $('retentionReport');
      if (!root || !root.classList.contains('is-fullscreen')) return;
      const toggle = $('retFullscreen');
      root.classList.remove('is-fullscreen');
      if (toggle) {
        toggle.setAttribute('aria-pressed', 'false');
        toggle.textContent = '全屏查看';
      }
    });
  }

  function mount(container) {
    if (!container) return;
    if ($('retentionReport')) return;   // research.js 已经挂过了

    const root = document.createElement('div');
    root.id = 'retentionReport';
    root.innerHTML = `
      <div class="ret-intro">
        <p class="ret-lead">这是刘宇翔的原始交付页，含六项分析（主线指标、玩法比较、完整过程、游玩投入、口碑、同类参照）和 1～5 款游戏的联动选择。面板只做嵌入，不重算任何统计，也不改写原页的选择与口径说明；数据快照、计算口径与来源文件都在页内「依据」区块。</p>
        <div class="ret-actions">
          <a class="ret-open" href="${SRC}" target="_blank" rel="noopener noreferrer">在新标签页打开 ↗</a>
          <button type="button" class="ghost ret-fullscreen" id="retFullscreen" aria-pressed="false">全屏查看</button>
        </div>
      </div>
      <div class="ret-frame-wrap" id="retFrameWrap">
        <iframe class="ret-frame" id="retFrame" src="${SRC}" title="实际完成曲线与游戏用户粘性：LYX 原始交互简报" loading="eager" referrerpolicy="no-referrer"></iframe>
      </div>
      <p class="ret-hint">页面较长，在框内直接滚动即可；想对照或打印时用上方「在新标签页打开」。iframe 内的「打印简报」行为随浏览器而异。</p>`;

    container.append(root);

    const toggle = $('retFullscreen');
    const setFull = (on) => {
      root.classList.toggle('is-fullscreen', on);
      toggle.setAttribute('aria-pressed', String(on));
      toggle.textContent = on ? '退出全屏' : '全屏查看';
    };
    toggle.addEventListener('click', () => setFull(!root.classList.contains('is-fullscreen')));
    bindEscape();
  }

  window.RetentionResearch = { mount };
})();
