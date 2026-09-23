/* Local-only forecast import. No upload, no modification of actual orders. */
(function (root) {
  'use strict';
  const MAX_BYTES = 5 * 1024 * 1024, MAX_XML = 20 * 1024 * 1024;
  function csvRows(text) {
    const rows = []; let row = [], cell = '', quoted = false;
    text = text.replace(/^\uFEFF/, '');
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (c === '"') {
        if (quoted && text[i + 1] === '"') { cell += '"'; i++; }
        else if (quoted || !cell) quoted = !quoted;
        else throw Error('CSV引号格式错误');
      } else if (!quoted && (c === ',' || c === '\n' || c === '\r')) {
        row.push(cell); cell = '';
        if (c !== ',') { rows.push(row); row = []; if (c === '\r' && text[i + 1] === '\n') i++; }
      } else cell += c;
    }
    if (quoted) throw Error('CSV引号未闭合');
    if (cell || row.length) { row.push(cell); rows.push(row); }
    return rows;
  }
  function isoDate(value, date1904) {
    if (typeof value === 'number') {
      if (!Number.isInteger(value) || value < 1 || value > 200000) return '';
      return new Date(Date.UTC(date1904 ? 1904 : 1899, date1904 ? 0 : 11, date1904 ? 1 : 30) + value * 86400000).toISOString().slice(0, 10);
    }
    const match = String(value ?? '').trim().match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$/);
    if (!match) return '';
    const result = match[1] + '-' + match[2].padStart(2, '0') + '-' + match[3].padStart(2, '0');
    const date = new Date(result + 'T00:00:00Z');
    return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === result ? result : '';
  }
  function normalize(rows, date1904 = false) {
    rows = rows.filter(row => row.some(value => String(value ?? '').trim()));
    if (rows.length < 2) throw Error('文件没有预测数据');
    if (rows.length > 20001) throw Error('最多支持20000条逐日记录');
    const headers = rows[0].map(value => String(value ?? '').trim());
    const index = names => headers.findIndex(header => names.includes(header));
    const model = index(['车型（代际）','车型','代际','代际名','历史传播名']);
    const date = index(['日期','预测日期']);
    const quantity = index(['预测数量','预测销量','逐日预测销量']);
    if ([model,date,quantity].includes(-1)) throw Error('表头需要：车型（代际）、日期、预测数量');
    const seen = new Set();
    return rows.slice(1).map((row,i) => {
      const name = String(row[model] ?? '').trim(), day = isoDate(row[date], date1904);
      const raw = row[quantity], value = Number(raw);
      if (!name || !day || raw == null || String(raw).trim() === '' || !Number.isSafeInteger(value) || value < 0)
        throw Error('第' + (i+2) + '行错误：车型不能为空，日期须为有效日期，数量须为非负整数');
      const key = name + '\0' + day;
      if (seen.has(key)) throw Error('第' + (i+2) + '行重复：同一车型同一天只能有一条记录');
      seen.add(key); return {model:name, date:day, quantity:value};
    });
  }
  async function xlsxRows(buffer) {
    const bytes = new Uint8Array(buffer), view = new DataView(buffer), decoder = new TextDecoder();
    let end = bytes.length - 22;
    while (end >= Math.max(0,bytes.length-65557) && view.getUint32(end,true) !== 0x06054b50) end--;
    if (end < 0 || view.getUint32(end,true) !== 0x06054b50) throw Error('不是有效的xlsx文件');
    const entries = new Map(), count = view.getUint16(end+10,true); let offset = view.getUint32(end+16,true), total = 0;
    if (count > 2000) throw Error('Excel文件包含过多内容，请仅保留预测数据');
    for (let i=0; i<count; i++) {
      if (view.getUint32(offset,true)!==0x02014b50) throw Error('Excel压缩目录损坏');
      const size=view.getUint32(offset+20,true), expanded=view.getUint32(offset+24,true);
      const length=view.getUint16(offset+28,true), extra=view.getUint16(offset+30,true), comment=view.getUint16(offset+32,true);
      const name=decoder.decode(bytes.slice(offset+46,offset+46+length));
      total+=expanded; if(total>MAX_XML) throw Error('Excel展开内容超过20MB，请精简文件');
      entries.set(name,{size,expanded,method:view.getUint16(offset+10,true),flags:view.getUint16(offset+8,true),offset:view.getUint32(offset+42,true)});
      offset+=46+length+extra+comment;
    }
    async function xml(name, optional=false) {
      const entry=entries.get(name);
      if(!entry) { if(optional)return null; throw Error('Excel缺少 '+name); }
      if(entry.flags&1) throw Error('不支持加密Excel');
      const start=entry.offset;
      if(view.getUint32(start,true)!==0x04034b50) throw Error('Excel文件损坏');
      const dataStart=start+30+view.getUint16(start+26,true)+view.getUint16(start+28,true);
      let content=bytes.slice(dataStart,dataStart+entry.size);
      if(entry.method===8) {
        const reader=new Blob([content]).stream().pipeThrough(new DecompressionStream('deflate-raw')).getReader();
        const chunks=[]; let size=0;
        while(true){const item=await reader.read();if(item.done)break;size+=item.value.length;if(size>MAX_XML||size>entry.expanded){await reader.cancel();throw Error('Excel解压内容超限');}chunks.push(item.value);}
        content=new Uint8Array(size);let pos=0;for(const chunk of chunks){content.set(chunk,pos);pos+=chunk.length;}
      } else if(entry.method!==0) throw Error('不支持的Excel压缩格式');
      const doc=new DOMParser().parseFromString(decoder.decode(content),'application/xml');
      if(doc.querySelector('parsererror'))throw Error('Excel XML格式错误');
      return doc;
    }
    const workbook=await xml('xl/workbook.xml'), rels=await xml('xl/_rels/workbook.xml.rels');
    const sheet=[...workbook.getElementsByTagName('sheet')].find(node=>node.getAttribute('state')!=='hidden'&&node.getAttribute('state')!=='veryHidden');
    if(!sheet)throw Error('Excel没有可见工作表');
    const id=sheet.getAttribute('r:id'),rel=[...rels.getElementsByTagName('Relationship')].find(node=>node.getAttribute('Id')===id);
    if(!rel||rel.getAttribute('TargetMode')==='External')throw Error('Excel工作表引用无效');
    const target=rel.getAttribute('Target'), sheetPath=target.startsWith('/')?target.slice(1):'xl/'+target.replace(/^\.\//,'');
    const shared=await xml('xl/sharedStrings.xml',true), strings=shared?[...shared.getElementsByTagName('si')].map(node=>[...node.getElementsByTagName('t')].map(t=>t.textContent).join('')):[];
    const sheetXml=await xml(sheetPath),rows=[];
    for(const node of sheetXml.getElementsByTagName('row')){
      const row=[];
      for(const cell of node.getElementsByTagName('c')){
        const address=cell.getAttribute('r')||'',letters=address.match(/^[A-Z]+/)?.[0];
        if(!letters)throw Error('Excel单元格地址无效');
        const column=[...letters].reduce((n,c)=>n*26+c.charCodeAt(0)-64,0)-1;
        if(column>100)throw Error('请仅保留预测数据列');
        const type=cell.getAttribute('t'),value=cell.getElementsByTagName('v')[0]?.textContent;
        row[column]=type==='s'?strings[Number(value)]:type==='inlineStr'?[...cell.getElementsByTagName('t')].map(t=>t.textContent).join(''):value==null?'':(!type||type==='n')?Number(value):value;
      }
      rows.push(row);
    }
    return normalize(rows,['1','true'].includes(workbook.getElementsByTagName('workbookPr')[0]?.getAttribute('date1904')));
  }
  async function read(file) {
    if(!file || file.size>MAX_BYTES)throw Error('请选择不超过5MB的文件');
    if(/\.xlsx$/i.test(file.name))return xlsxRows(await file.arrayBuffer());
    if(!/\.csv$/i.test(file.name))throw Error('仅支持.xlsx或UTF-8 CSV，请先另存旧版.xls');
    const text=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());
    return normalize(csvRows(text));
  }
  const api={read,normalize,csvRows};
  root.ForecastImport=api;
  if(typeof module==='object'&&module.exports)module.exports=api;
})(globalThis);
