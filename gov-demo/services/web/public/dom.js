// Tiny element builder. Text children are always set as text, never as HTML.
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== false && v !== null && v !== undefined) el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
}

export function field(label, id, input) {
  return [h("label", { for: id }, label), input];
}
