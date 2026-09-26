<template>
  <section class="page" data-module="tally">
    <header class="page-head">
      <div>
        <h2>理货作业管理</h2>
        <p class="page-desc">维护理货单，围绕理货单号、关联航次、理货方式、理货箱量做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记理货单</button>
        <button class="btn" type="button" @click="exportRows">导出理货作业清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无理货作业数据，可先登记理货单</td>
        </tr>
      </tbody>
    </table>

    <section class="review-panel">
      <header class="page-head">
        <div>
          <h3>理货差异复核</h3>
          <p class="page-desc">
            差异 = 理货箱量 − 残损箱数 − 随附箱量。差异为零直接通过；超出允许范围须人工复核，复核对不上须说明原因并退回；理货人员缺失或箱量为空的单独挑出。
          </p>
        </div>
      </header>

      <div class="filter-bar">
        <button
          v-for="tab in reviewTabs"
          :key="tab.scope"
          class="btn"
          :class="{ primary: reviewScope === tab.scope }"
          type="button"
          @click="switchScope(tab.scope)"
        >
          {{ tab.label }}（{{ summaryOf(tab.scope) }}）
        </button>
      </div>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in reviewColumns" :key="column">{{ column }}</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in reviews" :key="String(row.id)">
            <td v-for="column in reviewColumns" :key="column">
              <span :class="{ 'error-text': column === '判定结论' && isProblem(row) }">
                {{ row[column] ?? '—' }}
              </span>
            </td>
            <td class="row-actions">
              <template v-if="row['判定结论'] === '待复核'">
                <button class="link" type="button" @click="runReview('复核通过', row)">复核通过</button>
                <button class="link" type="button" @click="runReview('复核退回', row)">复核退回</button>
              </template>
              <span v-else>—</span>
            </td>
          </tr>
          <tr v-if="!reviews.length">
            <td :colspan="reviewColumns.length + 1" class="empty-state">当前范围内没有复核记录</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条理货作业记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/tally'
const columns = ["理货单号", "关联航次", "理货方式", "理货箱量", "残损箱数", "随附箱量", "理货人员", "完成时间", "理货状态"]
const actions = ["开始理货", "提交复核", "确认完成"]
const statuses = ["待理货", "理货中", "待复核", "已完成"]
const reviewColumns = ["理货单号", "理货箱量", "残损箱数", "随附箱量", "差异", "判定结论", "缺项说明", "退回原因", "复核人", "复核时间"]
const reviewTabs = [
  { scope: 'all', label: '全部' },
  { scope: 'pending', label: '待复核' },
  { scope: 'incomplete', label: '资料不全' },
  { scope: 'passed', label: '已通过' },
  { scope: 'returned', label: '已退回' },
]
const scopeLabels: Record<string, string> = { pending: '待复核', incomplete: '资料不全', passed: '已通过', returned: '已退回' }
const problemConclusions = ['待复核', '资料不全', '复核退回']

const rows = ref<Row[]>([])
const reviews = ref<Row[]>([])
const reviewSummary = ref<Record<string, number>>({})
const reviewScope = ref('all')
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const stats = computed(() => [
  { label: '待复核', value: reviewSummary.value['待复核'] ?? 0 },
  { label: '资料不全', value: reviewSummary.value['资料不全'] ?? 0 },
  { label: '已通过', value: reviewSummary.value['已通过'] ?? 0 },
  { label: '已退回', value: reviewSummary.value['已退回'] ?? 0 },
])

function summaryOf(scope: string) {
  if (scope === 'all') {
    return Object.values(reviewSummary.value).reduce((sum, value) => sum + value, 0)
  }
  return reviewSummary.value[scopeLabels[scope]] ?? 0
}

function isProblem(row: Row) {
  return problemConclusions.includes(String(row['判定结论'] ?? ''))
}

function switchScope(scope: string) {
  reviewScope.value = scope
  void reloadReviews()
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '理货单登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? '理货作业动作未生效，请稍后重试')
    }
    await Promise.all([reload(), reloadReviews()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '理货作业操作失败'
  }
}

async function runReview(decision: string, row: Row) {
  errorMessage.value = ''
  let reason = ''
  if (decision === '复核退回') {
    reason = window.prompt('复核对不上，请填写退回原因')?.trim() ?? ''
    if (!reason) {
      errorMessage.value = '复核退回必须说明原因'
      return
    }
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/review`, {
      method: 'POST',
      body: JSON.stringify({ values: { decision, reason } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? '复核结论未生效，请稍后重试')
    }
    await Promise.all([reload(), reloadReviews()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复核操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('理货单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '理货作业列表读取失败'
  }
}

async function reloadReviews() {
  try {
    const response = await request(`${ENDPOINT}/reviews?scope=${reviewScope.value}`)
    if (!response.ok) {
      throw new Error('复核结论读取失败')
    }
    const payload = await response.json()
    reviews.value = payload.items ?? []
    reviewSummary.value = payload.summary ?? {}
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复核结论读取失败'
  }
}

onMounted(() => {
  void reload()
  void reloadReviews()
})
</script>
