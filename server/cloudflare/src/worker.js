const MAX_FILE = 25 * 1024 * 1024;
const MAX_ROOM_BYTES = 100 * 1024 * 1024;
const CHUNK_BYTES = 256 * 1024;
const TTL = 24 * 60 * 60 * 1000;
const json = (data, status = 200) => Response.json(data, {status, headers: {"Cache-Control": "no-store"}});
const fail = (message, status = 400) => json({error: message}, status);
const randomKey = () => Array.from(crypto.getRandomValues(new Uint8Array(32)), b => b.toString(16).padStart(2, "0")).join("");
async function digest(value) {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value))), b => b.toString(16).padStart(2, "0")).join("");
}
async function body(request) {
  if (Number(request.headers.get("Content-Length")) > 16384) throw new Error("요청이 너무 큽니다.");
  const reader = request.body?.getReader();
  if (!reader) throw new Error("요청 내용이 없습니다.");
  const chunks = []; let length = 0;
  try {
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > 16384) throw new Error("요청이 너무 큽니다.");
      chunks.push(value);
    }
  } finally { await reader.cancel(); }
  const result = new Uint8Array(length); let offset = 0;
  for (const chunk of chunks) {result.set(chunk, offset); offset += chunk.length;}
  return JSON.parse(new TextDecoder().decode(result));
}

export default {
  async fetch(request, env) {
    try {
      if (!env.SERVICE_TOKEN) return fail("서버 SERVICE_TOKEN 설정이 필요합니다.", 503);
      if (await digest(request.headers.get("Authorization") || "") !== await digest(`Bearer ${env.SERVICE_TOKEN}`)) return fail("서버 인증에 실패했습니다.", 401);
      const url = new URL(request.url);
      if (url.pathname === "/rooms" && request.method === "POST") {
        const id = crypto.randomUUID().replaceAll("-", "");
        const key = randomKey();
        const stub = env.ROOMS.get(env.ROOMS.idFromName(id));
        return stub.fetch(new Request(`https://room/internal/create`, {method: "POST", body: JSON.stringify({id, key})}));
      }
      const match = url.pathname.match(/^\/rooms\/([a-f0-9]{32})\/(join|events|files\/[a-f0-9-]{36})$/);
      if (!match) return fail("경로를 찾을 수 없습니다.", 404);
      return env.ROOMS.get(env.ROOMS.idFromName(match[1])).fetch(request);
    } catch { return fail("서버 요청 처리에 실패했습니다.", 500); }
  }
};

export class TransferRoom {
  constructor(ctx, env) {
    this.ctx = ctx; this.env = env; this.sql = ctx.storage.sql;
    this.sql.exec("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)");
    this.sql.exec("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT)");
    this.sql.exec("CREATE TABLE IF NOT EXISTS files (id TEXT PRIMARY KEY, name TEXT, size INTEGER, ready INTEGER DEFAULT 0)");
    this.sql.exec("CREATE TABLE IF NOT EXISTS chunks (file TEXT, part INTEGER, bytes BLOB, PRIMARY KEY(file, part))");
    this.uploading = false;
  }
  meta(key) {return this.sql.exec("SELECT value FROM meta WHERE key = ?", key).toArray()[0]?.value;}
  event(data) {
    this.sql.exec("INSERT INTO events(payload) VALUES (?)", JSON.stringify({...data, time: Date.now()}));
    this.sql.exec("DELETE FROM events WHERE id <= (SELECT MAX(id) - 500 FROM events)");
  }
  async storeFile(id, request, size) {
    const reader = request.body?.getReader();
    if (!reader) throw new Error("empty body");
    let received = 0, used = 0, part = 0;
    const buffer = new Uint8Array(CHUNK_BYTES);
    const flush = () => {
      if (!this.meta("id") || Date.now() >= Number(this.meta("expires"))) throw new Error("expired room");
      this.sql.exec("INSERT INTO chunks(file, part, bytes) VALUES (?, ?, ?)", id, part++, buffer.slice(0, used));
      used = 0;
    };
    try {
      while (true) {
        const {value, done} = await reader.read();
        if (done) break;
        received += value.byteLength;
        if (received > size) throw new Error("file too large");
        for (let offset = 0; offset < value.byteLength;) {
          const length = Math.min(CHUNK_BYTES - used, value.byteLength - offset);
          buffer.set(value.subarray(offset, offset + length), used);
          used += length; offset += length;
          if (used === CHUNK_BYTES) flush();
        }
      }
      if (received !== size) throw new Error("incomplete file");
      if (used) flush();
    } finally {await reader.cancel();}
  }
  async fetch(request) {
    try {
      const url = new URL(request.url);
      if (url.pathname === "/internal/create" && request.method === "POST") {
        if (this.meta("id")) return fail("이미 생성된 방입니다.", 409);
        const {id, key} = await body(request);
        const hash = await digest(key);
        const expires = Date.now() + TTL;
        this.sql.exec("INSERT INTO meta VALUES ('id', ?), ('hash', ?), ('expires', ?)", id, hash, String(expires));
        await this.ctx.storage.setAlarm(expires);
        return json({id, key, expires}, 201);
      }
      if (!this.meta("id") || Date.now() >= Number(this.meta("expires"))) return fail("방이 없거나 만료되었습니다.", 404);
      if (await digest(request.headers.get("X-Room-Key") || "") !== this.meta("hash")) return fail("방 코드가 올바르지 않습니다.", 403);
      const action = url.pathname.split("/")[3];
      if (action === "join" && request.method === "POST") return json({expires: Number(this.meta("expires")), region: request.cf?.colo || "자동"});
      if (action === "events" && request.method === "GET") {
        const after = Number(url.searchParams.get("after") || 0);
        if (!Number.isSafeInteger(after) || after < 0) return fail("잘못된 커서입니다.");
        return json({events: this.sql.exec("SELECT id, payload FROM events WHERE id > ? ORDER BY id LIMIT 100", after).toArray().map(row => ({id: row.id, ...JSON.parse(row.payload)}))});
      }
      if (action === "events" && request.method === "POST") {
        const data = await body(request);
        if (typeof data.text !== "string" || !data.text.trim() || data.text.length > 4000 || typeof data.name !== "string" || !data.name.trim() || data.name.length > 40) return fail("이름 또는 메시지 길이를 확인하세요.");
        this.event({type: "chat", text: data.text, name: data.name});
        return json({ok: true});
      }
      if (action === "files") {
        const id = url.pathname.split("/")[4];
        if (request.method === "PUT") {
          const size = Number(request.headers.get("Content-Length"));
          let name;
          try {name = decodeURIComponent(request.headers.get("X-File-Name") || "");} catch {return fail("파일명이 올바르지 않습니다.");}
          if (!name || name.length > 240 || /[\x00-\x1f/\\]/.test(name)) return fail("파일명이 올바르지 않습니다.");
          if (!Number.isSafeInteger(size) || size <= 0 || size > MAX_FILE) return fail("파일은 1바이트~25 MiB까지 전송할 수 있습니다.", 413);
          if (this.sql.exec("SELECT COUNT(*) AS n FROM files").toArray()[0].n >= 100) return fail("방의 파일 한도(100개)에 도달했습니다.", 429);
          if (this.sql.exec("SELECT id FROM files WHERE id = ?", id).toArray().length) return fail("중복 파일입니다.", 409);
          if (this.uploading) return fail("다른 파일을 업로드 중입니다. 잠시 후 다시 시도하세요.", 429);
          const stored = this.sql.exec("SELECT COALESCE(SUM(size), 0) AS bytes FROM files").toArray()[0].bytes;
          if (stored + size > MAX_ROOM_BYTES) return fail("방의 파일 저장 한도(100 MiB)에 도달했습니다. 새 방을 만드세요.", 413);
          this.sql.exec("INSERT INTO files(id, name, size) VALUES (?, ?, ?)", id, name, size);
          this.uploading = true;
          try {
            await this.storeFile(id, request, size);
            if (!this.meta("id") || Date.now() >= Number(this.meta("expires"))) {
              throw new Error("expired room");
            }
            this.sql.exec("UPDATE files SET ready = 1 WHERE id = ?", id);
            this.event({type: "file", file: id, name, size});
            return json({ok: true, file: id});
          } catch {
            this.sql.exec("DELETE FROM chunks WHERE file = ?", id);
            this.sql.exec("DELETE FROM files WHERE id = ?", id);
            return fail("파일 저장에 실패했습니다.", 502);
          } finally {this.uploading = false;}
        }
        if (request.method === "GET") {
          const file = this.sql.exec("SELECT * FROM files WHERE id = ? AND ready = 1", id).toArray()[0];
          if (!file) return fail("파일을 찾을 수 없습니다.", 404);
          let part = 0, sent = 0;
          const sql = this.sql;
          const stream = new ReadableStream({pull(controller) {
            if (sent === file.size) {controller.close(); return;}
            const chunk = sql.exec("SELECT bytes FROM chunks WHERE file = ? AND part = ?", id, part++).toArray()[0];
            if (!chunk) {controller.error(new Error("파일이 만료되었거나 손상되었습니다.")); return;}
            const bytes = new Uint8Array(chunk.bytes);
            sent += bytes.byteLength;
            controller.enqueue(bytes);
          }});
          return new Response(stream, {headers: {"Content-Type": "application/octet-stream", "Content-Length": String(file.size), "Content-Disposition": `attachment; filename*=UTF-8''${encodeURIComponent(file.name)}`, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}});
        }
      }
      return fail("지원하지 않는 요청입니다.", 405);
    } catch {return fail("요청 내용을 확인하세요.", 400);}
  }
  async alarm() {
    // Keep the schema available for in-flight requests on this same instance.
    this.sql.exec("DELETE FROM chunks");
    this.sql.exec("DELETE FROM events");
    this.sql.exec("DELETE FROM files");
    this.sql.exec("DELETE FROM meta");
  }
}
