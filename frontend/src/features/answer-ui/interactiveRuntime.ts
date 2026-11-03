/** A model document is data until mounted in an opaque-origin sandbox. */
export type InteractiveCard = {
  type: "interactive";
  id: string;
  revision: number;
  title: string;
  summary: string;
  html: string;
};

export const INTERACTIVE_CONTEXT = `【自由交互界面 v1】
需要自定义交互时，在 study-ui JSON 中输出 {"type":"interactive","id":"稳定的英文短标识","revision":1,"title":"具体标题","summary":"不用交互也能读懂的机制、假设与操作提示","html":"完整、自包含的HTML内容"}。代码围栏的语言必须是study-ui，不能改为json或html，否则只显示源码。html最多60000字符，可包含内联style、script、SVG、Canvas；无需局限于预设模板。先给有用文字，生成完整块后界面即可使用。
按问题选择表达方式：拖参数观察因果、逐步运行并同步代码/对象/说明、选择条件比较结果。所有控件操作必须真的改变同一状态，提供初始状态和重置。逐步执行时，尚未创建的对象不能画成已存在的实体；前进、后退、重置后图形和说明都从当前状态推导。不要生成假按钮或只有装饰的图。数据和计算要明确区分示意、假设、真实测量；图不是核验证据。
使用原生DOM和addEventListener；无外部依赖、CDN、导入、网络请求、表单提交、链接跳转、弹窗、文件或存储访问。只使用本块显式给出的数据，不访问父页面。script中的</script>保持正常HTML语法，整个html必须正确JSON转义。
布局适应240px到900px，正文至少14px、控件至少40px；白底深字、少量有含义的强调色。SVG用viewBox，但文字需按最终缩放后的显示尺寸保持至少14px；放不下时改布局、用HTML标签或局部滚动，不把整图缩成小字。Canvas随容器尺寸绘制并提供文字等价说明。输入需label，输出用output或有标签的区域，键盘可操作；动画可暂停并尊重prefers-reduced-motion。
界面已提供window.studyUI.setState({参数名:值,观察:简短说明})。初始化与每次操作后调用它，把当前探索状态提供给用户的“带着当前状态继续问”按钮；仅JSON对象，序列化最多4000字符，无敏感信息。不要把用户参数当作已核验事实。未调用时，应用只记录带name/id的普通表单控件。需要支持“恢复上次状态”时，调用window.studyUI.onRestore(snapshot => { ... })，用快照字段重建同一状态；快照可能来自旧版本，字段缺失时回退到初始状态而不是报错。
收到对此界面的追问时，结合随问题附带的参数和观察修改；输出同id、revision加1的完整新版本，不输出补丁，旧版本会留在原回答。保留用户当前参数，除非其要求重置。界面失败时仍以summary和正文解释原理。`;

export function stateText(value: unknown): string | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  try {
    const text = JSON.stringify(value);
    return text.length <= 4000 ? text : null;
  } catch { return null; }
}

// The template is inert: parsing a model's HTML must never execute scripts or
// fetch images in the parent document. This is hygiene, not the security boundary.
function makeSandboxContent(html: string, channel: string): string {
  const template = document.createElement("template");
  template.innerHTML = html;
  template.content.querySelectorAll("base,meta,iframe,frame,frameset,object,embed,link").forEach(el => el.remove());
  template.content.querySelectorAll("*").forEach(el => {
    for (const attr of Array.from(el.attributes)) {
      const name = attr.name.toLowerCase();
      if (name.startsWith("on") || ["srcdoc", "action", "formaction", "target", "ping", "download"].includes(name)) el.removeAttribute(attr.name);
      if ((name === "href" || name === "xlink:href") && !attr.value.startsWith("#")) el.removeAttribute(attr.name);
    }
  });
  const policy = "default-src 'none'; script-src 'unsafe-inline'; script-src-attr 'none'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; font-src 'none'; media-src 'none'; frame-src 'none'; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
  // No incoming messages or host data are provided. Capturing postMessage keeps
  // ordinary model globals from accidentally breaking the small outgoing bridge.
  const bridge = `(() => {
    const send = parent.postMessage.bind(parent);
    const channel = ${JSON.stringify(channel)};
    let latest = {};
    let restoreHandler = null;
    const emit = (type, value) => send({channel, type, value}, '*');
    const publish = value => {
      if (!value || typeof value !== 'object' || Array.isArray(value)) return;
      try { const encoded = JSON.stringify(value); if (encoded.length <= 4000) { latest = JSON.parse(encoded); emit('state', latest); } } catch {}
    };
    Object.defineProperty(window, 'studyUI', {value: Object.freeze({
      setState: publish,
      // The host owns persistence; the document only rebuilds itself from a
      // snapshot it accepts. A document that never registers cannot be restored.
      onRestore: handler => { if (typeof handler === 'function') restoreHandler = handler; }
    }), writable: false});
    addEventListener('error', event => emit('error', String(event.message).slice(0, 500)));
    addEventListener('unhandledrejection', event => emit('error', String(event.reason).slice(0, 500)));
    addEventListener('submit', event => event.preventDefault(), true);
    addEventListener('message', event => {
      const data = event.data;
      if (!data || data.channel !== channel || data.type !== 'restore') return;
      if (typeof restoreHandler !== 'function') { emit('restore_unavailable', true); return; }
      try { restoreHandler(JSON.parse(JSON.stringify(data.value))); }
      catch (error) { emit('error', String(error).slice(0, 500)); }
    });
    const controls = () => {
      const values = Object.create(null);
      document.querySelectorAll('input,select,textarea').forEach(el => {
        const key = el.name || el.id;
        if (!key || ['password','file','hidden','submit','button'].includes(el.type)) return;
        if (el.type === 'radio' && !el.checked) return;
        values[key] = el.type === 'checkbox' ? el.checked : el.value;
      });
      publish({...latest, controls: values});
    };
    const changed = () => queueMicrotask(controls);
    addEventListener('input', changed); addEventListener('change', changed);
    addEventListener('DOMContentLoaded', () => {
      controls();
      new ResizeObserver(() => emit('height', document.body.scrollHeight)).observe(document.body);
      emit('ready', true);
    });
  })();`;
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${policy}"><meta name="referrer" content="no-referrer"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
    :root { color-scheme: light; font: 15px/1.65 system-ui, sans-serif; color: #262626; background: white; }
    * { box-sizing: border-box; } body { margin: 0; padding: 20px; overflow-wrap: anywhere; }
    img,svg,canvas { max-width: 100%; } button,input,select,textarea { font: inherit; max-width: 100%; }
    button { min-height: 40px; cursor: pointer; } :focus-visible { outline: 2px solid #39765d; outline-offset: 3px; }
    @media(max-width: 400px) { body { padding: 12px; } }
    @media(prefers-reduced-motion:reduce) { *,*::before,*::after { animation: none !important; transition: none !important; scroll-behavior: auto !important; } }
  </style><script>${bridge}</script></head><body>${template.innerHTML}</body></html>`;
}

export function makeInteractiveDocument(html: string, channel: string): string {
  // A second, trusted frame owns frame-src. CSP in the generated document
  // alone cannot block that document navigating itself to an external URL.
  // srcdoc is local; subsequent URL navigations are constrained by this parent.
  const source = JSON.stringify(makeSandboxContent(html, channel)).replace(/</g, "\\u003c");
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-src 'none'; base-uri 'none'; form-action 'none'"><style>html,body{margin:0;width:100%;height:100%;overflow:hidden}iframe{display:block;border:0;width:100%;height:100%}</style></head><body><script>
    const channel = ${JSON.stringify(channel)};
    const canvas = document.createElement('iframe');
    canvas.title = '交互内容';
    canvas.setAttribute('sandbox', 'allow-scripts');
    canvas.setAttribute('referrerpolicy', 'no-referrer');
    canvas.srcdoc = ${source};
    addEventListener('message', event => {
      const data = event.data;
      if (!data || data.type !== 'restore' || data.channel !== channel) return;
      try { canvas.contentWindow.postMessage({channel, type: 'restore', value: data.value}, '*'); } catch {}
    });
    addEventListener('message', event => {
      if (event.source !== canvas.contentWindow || event.origin !== 'null') return;
      const data = event.data;
      if (!data || typeof data !== 'object' || data.channel !== channel) return;
      if (['ready','height','state','error','restore_unavailable'].includes(data.type)) parent.postMessage(data, '*');
    });
    document.body.append(canvas);
  </script></body></html>`;
}

export function interactiveFollowup(card: InteractiveCard, state: string | null, error = ""): string {
  return `继续探索「${card.title}」（版本 ${card.revision}）。\n当前参数与观察：${state ?? "尚未提供状态；请使用原界面初始参数。"}\n${error ? `运行错误：${error}\n请修复这个界面，保留原有功能。` : "请结合当前状态解释变化，并按我的补充修改界面。"}`;
}
