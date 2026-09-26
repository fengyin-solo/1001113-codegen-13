<template>
  <section class="page" data-module="tally-review">
    <header class="page-head">
      <div>
        <h2>理货差异复核</h2>
        <p class="page-desc">
          按理货单的理货箱量、残损箱数与随附记录逐项对差。判定口径：箱量差异不超过
          ±{{ tolerance['箱量允许差异'] }} 箱、残损箱数差异不超过 {{ tolerance['残损箱数允许差异'] }} 箱（差异为零直接通过）；
          超出范围的须说明原因并退回理货岗返工。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="reload">刷新重算差异</button>
        <button class="btn" type="button" @click="exportRows">导出复核台账</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statsCards" :key="item.key" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>理货单号</span>
        <input v-model="keyword" placeholder="按理货单号检索" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetKeyword">清空关键字</button>
    </form>

    <nav class="tab-bar">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        class="tab-item"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
        <span class="tab-count">{{ summary.counts[tab.key] ?? 0 }}</span>
      </button>
    </nav>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row['理货单号'] ?? '—' }}</td>
          <td>{{ row['关联航次'] ?? '—' }}</td>
          <td>{{ row['理货人员'] || '—' }}</td>
          <td>{{ row['理货箱量'] ?? '—' }}</td>
          <td>{{ row['残损箱数'] ?? 0 }}</td>
          <td>{{ row['随附箱量'] ?? '—' }}</td>
          <td>{{ row['随附残损数'] ?? '—' }}</td>
          <td>
            <span v-if="row['箱量差异'] === null">—</span>
            <span :class="{ 'diff-over': row['在允许范围'] === false }">{{ formatDiff(row['箱量差异']) }}</span>
          </td>
          <td>
            <span v-if="row['残损差异'] === null">—</span>
            <span :class="{ 'diff-over': row['在允许范围'] === false }">{{ formatDiff(row['残损差异']) }}</span>
          </td>
          <td>
            <span class="badge" :class="badgeClass(row['判定'])">{{ row['判定'] }}</span>
            <div v-if="row['与理货单一致'] === false" class="cell-hint warn">
              结论基于旧数据：箱量 {{ row['理货箱量'] }} 箱，重新提交可刷新结论
            </div>
          </td>
          <td>
            <template v-if="row['复核人员']">{{ row['复核人员'] }}<div class="cell-hint">{{ row['复核时间'] }}</div></template>
            <span v-else>—</span>
          </td>
          <td>
            <span v-if="!row['资料齐']" class="cell-hint warn">缺失：{{ missingText(row) }}，请补齐后再复核</span>
            <span v-else-if="row['复核原因']">{{ row['复核原因'] }}</span>
            <span v-else class="cell-hint">差异为零或在允许范围内，提交即通过</span>
          </td>
          <td class="row-actions">
            <button
              v-if="row['资料齐']"
              class="link"
              type="button"
              @click="openReview(row)"
            >
              {{ row['随附箱量'] === null ? '提交复核' : '重新复核' }}
            </button>
            <span v-else class="cell-hint warn">暂不可复核</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">当前口径下暂无理货单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ rows.length }} 条理货单（差异每次刷新按理货单当前数据重算）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else-if="successMessage" class="success-text">{{ successMessage }}</span>
    </footer>

    <div v-if="reviewTarget" class="modal-mask" @click.self="closeReview">
      <div class="modal-card">
        <h3 class="modal-title">复核 {{ reviewTarget['理货单号'] }}</h3>
        <p class="modal-sub">
          理货箱量 {{ reviewTarget['理货箱量'] }} 箱、残损 {{ reviewTarget['残损箱数'] ?? 0 }} 箱；
          允许范围 ±{{ tolerance['箱量允许差异'] }} 箱 / 残损 {{ tolerance['残损箱数允许差异'] }} 箱。
        </p>
        <div class="form-grid">
          <label class="form-item">
            <span>随附记录箱量 *</span>
            <input v-model="form.随附箱量" type="number" placeholder="随附记录中的箱量" />
          </label>
          <label class="form-item">
            <span>随附残损箱数 *</span>
            <input v-model="form.随附残损数" type="number" placeholder="随附记录中的残损箱数" />
          </label>
          <label class="form-item">
            <span>复核人员 *</span>
            <input v-model="form.复核人员" placeholder="填写复核人姓名" />
          </label>
          <label class="form-item form-wide">
            <span>退回原因（差异超出允许范围时必填）</span>
            <textarea v-model="form.复核原因" rows="3" placeholder="对不上时说明原因，随退回单一并发给理货岗"></textarea>
          </label>
        </div>
        <div class="modal-preview">
          <template v-if="preview.boxDiff === null">
            <span class="cell-hint">请先填写随附记录箱量</span>
          </template>
          <template v-else>
            箱量差异 <b :class="{ 'diff-over': !preview.within }">{{ formatDiff(preview.boxDiff) }}</b>
            箱 · 残损差异 <b :class="{ 'diff-over': !preview.within }">{{ formatDiff(preview.damageDiff) }}</b>
            箱 →
            <span v-if="preview.within" class="badge badge-approved">在允许范围内，提交即通过结单</span>
            <span v-else class="badge badge-returned">超出允许范围，提交后退回返工</span>
          </template>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="closeReview">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitReview">
            {{ submitting ? '提交中…' : '提交复核结论' }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null | boolean | string[]>
type Counts = Record<string, number>

const ENDPOINT = '/api/tally-review'
const columns = [
  '理货单号',
  '关联航次',
  '理货人员',
  '理货箱量',
  '残损箱数',
  '随附箱量',
  '随附残损数',
  '箱量差异',
  '残损差异',
  '判定',
  '复核信息',
  '原因/缺失',
]

const tabs = [
  { key: '待复核', label: '待复核' },
  { key: '资料不齐', label: '资料不齐' },
  { key: '已变更待重核', label: '已变更待重核' },
  { key: '复核通过', label: '复核通过' },
  { key: '复核退回', label: '复核退回' },
]

const rows = ref<Row[]>([])
const counts = ref<Counts>({})
const tolerance = ref<Record<string, number>>({ 箱量允许差异: 2, 残损箱数允许差异: 0 })
const activeTab = ref('待复核')
const keyword = ref('')
const errorMessage = ref('')
const successMessage = ref('')

const reviewTarget = ref<Row | null>(null)
const submitting = ref(false)
const form = reactive({ 随附箱量: '', 随附残损数: '0', 复核人员: '', 复核原因: '' })

const summary = computed(() => ({ counts: counts.value }))

const statsCards = computed(() => [
  { key: '待复核', label: '待复合理货单', value: counts.value['待复核'] ?? 0 },
  { key: '资料不齐', label: '资料不齐（人员缺失/箱量为空）', value: counts.value['资料不齐'] ?? 0 },
  { key: '已变更待重核', label: '结论已过期待重核', value: counts.value['已变更待重核'] ?? 0 },
  { key: '复核通过', label: '复核通过已结单', value: counts.value['复核通过'] ?? 0 },
  { key: '复核退回', label: '复核退回返工中', value: counts.value['复核退回'] ?? 0 },
])


const preview = computed(() => {
  const target = reviewTarget.value
  if (!target) return { boxDiff: null as number | null, damageDiff: 0, within: false }
  const box = parseNum(form.随附箱量)
  const damage = parseNum(form.随附残损数)
  if (box === null) return { boxDiff: null, damageDiff: 0, within: false }
  const tallyBox = Number(target['理货箱量'])
  const tallyDamage = Number(target['残损箱数'] ?? 0)
  const boxDiff = tallyBox - box
  const damageDiff = tallyDamage - (damage ?? 0)
  const within =
    Math.abs(boxDiff) <= (tolerance.value['箱量允许差异'] ?? 0) &&
    Math.abs(damageDiff) <= (tolerance.value['残损箱数允许差异'] ?? 0)
  return { boxDiff, damageDiff, within }
})

function parseNum(value: string): number | null {
  const text = String(value ?? '').trim()
  if (!text) return null
  const num = Number(text)
  return Number.isFinite(num) ? num : null
}

function formatDiff(value: unknown): string {
  if (value === null || value === undefined) return '—'
  const num = Number(value)
  return num > 0 ? `+${num}` : String(num)
}

function missingText(row: Row): string {
  const missing = row['缺失项']
  return Array.isArray(missing) ? missing.join('、') : String(missing ?? '')
}

function badgeClass(judge: unknown): string {
  if (judge === '复核通过') return 'badge-approved'
  if (judge === '复核退回') return 'badge-returned'
  if (judge === '资料不齐') return 'badge-incomplete'
  if (judge === '已变更待重核') return 'badge-stale'
  return 'badge-pending'
}

function resetKeyword() {
  keyword.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openReview(row: Row) {
  reviewTarget.value = row
  form.随附箱量 = row['随附箱量'] === null || row['随附箱量'] === undefined ? '' : String(row['随附箱量'])
  form.随附残损数 = row['随附残损数'] === null || row['随附残损数'] === undefined ? '0' : String(row['随附残损数'])
  form.复核人员 = String(row['复核人员'] ?? '')
  form.复核原因 = String(row['复核原因'] ?? '')
  errorMessage.value = ''
  successMessage.value = ''
}

function closeReview() {
  reviewTarget.value = null
  submitting.value = false
}

async function submitReview() {
  if (!reviewTarget.value) return
  submitting.value = true
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${reviewTarget.value.id}/review`, {
      method: 'POST',
      body: JSON.stringify({
        values: {
          随附箱量: parseNum(form.随附箱量),
          随附残损数: parseNum(form.随附残损数) ?? 0,
          复核人员: form.复核人员,
          复核原因: form.复核原因,
        },
      }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.detail || payload.message || '复核未生效，请稍后重试')
    }
    successMessage.value = payload.message
    closeReview()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复核提交失败'
  } finally {
    submitting.value = false
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const query = new URLSearchParams({ judge: activeTab.value, size: '200' })
    if (keyword.value.trim()) query.set('keyword', keyword.value.trim())
    const [listResp, summaryResp] = await Promise.all([
      request(`${ENDPOINT}?${query.toString()}`),
      request(`${ENDPOINT}/summary`),
    ])
    if (!listResp.ok) throw new Error('复核工作台读取失败')
    const listPayload = await listResp.json()
    const summaryPayload = await summaryResp.json()
    rows.value = (listPayload.items ?? []) as Row[]
    counts.value = (summaryPayload.counts ?? {}) as Counts
    tolerance.value = (summaryPayload.允许范围 ?? tolerance.value) as Record<string, number>
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复核工作台读取失败'
  }
}

watch(activeTab, () => {
  void reload()
})

onMounted(reload)
</script>
