// Local protocol integration harness using the actual Worker and SQLite code.
import http from 'node:http';
import {environment} from '../server/cloudflare/test/harness.js';
const harness = environment();
const server = http.createServer(async (req, res) => {
  try {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const response = await harness.fetch(new Request(`http://localhost${req.url}`, {method: req.method, headers: req.headers, ...(['GET', 'HEAD'].includes(req.method) ? {} : {body: Buffer.concat(chunks)})}));
    res.writeHead(response.status, Object.fromEntries(response.headers));
    res.end(Buffer.from(await response.arrayBuffer()));
  } catch (error) {res.writeHead(500); res.end(String(error));}
});
server.listen(0, '127.0.0.1', () => process.stdout.write(String(server.address().port) + '\n'));
