// L3 功能场景测试（Phase 6 评测 CLI，M22）
import { execFileSync } from 'node:child_process'
import { readFileSync, rmSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = join(__dirname, '../..')
const OUT = join(__dirname, '../results')
mkdirSync(OUT, { recursive: true })
const results = []

async function scenario(id, module, fn) {
  try {
    await fn()
    results.push({ id, module, status: 'PASS' })
    console.log(`PASS ${id}`)
  } catch (e) {
    results.push({ id, module, status: 'FAIL', error: String(e).slice(0, 400) })
    console.log(`FAIL ${id}: ${String(e).slice(0, 250)}`)
  }
}

await scenario('L3M22-01', 'M22', () => {
  const outDir = join(ROOT, 'qa/evaluation/reports/functional_test')
  rmSync(outDir, { recursive: true, force: true })
  const stdout = execFileSync(
    join(ROOT, 'backend/.venv/bin/python'),
    [join(ROOT, 'qa/evaluation/evaluate_phase6.py'), '--subset', 'smoke', '--skip-ocr', '--output-dir', outDir],
    { encoding: 'utf-8', env: { ...process.env, PYTHONPATH: join(ROOT, 'backend') } },
  )
  if (!stdout.includes('门禁结论：PASS')) throw new Error('CLI 未输出 PASS')
  const report = JSON.parse(readFileSync(join(outDir, 'phase6_metrics.json'), 'utf-8'))
  if (report.metrics.task_success_rate !== 1.0) throw new Error(`任务成功率异常：${report.metrics.task_success_rate}`)
  if (!report.gates || !('layout_recall' in report.gates)) throw new Error('门禁字段缺失')
  if (!readFileSync(join(outDir, 'phase6_report.md'), 'utf-8').includes('Phase 6 评测报告')) throw new Error('报告文件异常')
  rmSync(outDir, { recursive: true, force: true })
})

const failed = results.filter((r) => r.status === 'FAIL')
const { writeFileSync } = await import('node:fs')
writeFileSync(join(OUT, 'phase6_cli_results.json'), JSON.stringify({ total: results.length, passed: results.length - failed.length, failed: failed.length, results }, null, 2))
console.log(`PHASE6_CLI_DONE total=${results.length} passed=${results.length - failed.length} failed=${failed.length}`)
if (failed.length) process.exitCode = 1
