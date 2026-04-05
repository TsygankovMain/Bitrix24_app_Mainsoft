<script setup lang="ts">
import { computed, ref } from 'vue'
import ProjectBoardCard from '~/components/projects/ProjectBoardCard.vue'
import type { ProjectBoardCardRecord } from '~/utils/projectBoard'
import { getStageColumnClass } from '~/utils/projectBoard'

const props = defineProps<{
  title: string
  stage: string
  cards: ProjectBoardCardRecord[]
  canDrop: boolean
}>()

const emit = defineEmits<{
  (event: 'edit', card: ProjectBoardCardRecord): void
  (event: 'dragstart', projectId: string): void
  (event: 'drop-card', payload: { projectId: string; stage: string }): void
}>()

const isDragOver = ref(false)
const columnClass = computed(() => getStageColumnClass(props.stage))

function handleDragOver() {
  if (!props.canDrop) {
    return
  }

  isDragOver.value = true
}

function handleDragLeave() {
  isDragOver.value = false
}

function handleDrop(event: DragEvent) {
  isDragOver.value = false
  if (!props.canDrop) {
    return
  }

  const projectId = event.dataTransfer?.getData('text/plain')
  if (!projectId) {
    return
  }

  emit('drop-card', {
    projectId,
    stage: props.stage
  })
}
</script>

<template>
  <section
    :class="[
      'flex min-h-[540px] w-[320px] flex-col rounded-3xl border border-slate-200 bg-gradient-to-b p-4 shadow-sm transition',
      columnClass,
      isDragOver ? 'border-lime-400 shadow-lg' : ''
    ]"
    @dragover.prevent="handleDragOver"
    @dragleave="handleDragLeave"
    @drop.prevent="handleDrop"
  >
    <div class="mb-4 flex items-center justify-between gap-3">
      <div>
        <h3 class="text-sm font-semibold text-slate-900">{{ title }}</h3>
        <p class="mt-1 text-xs text-slate-500">
          {{ canDrop ? 'Перетащите карточку сюда' : 'Статус назначается автоматически' }}
        </p>
      </div>
      <div class="rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-700 shadow-sm">
        {{ cards.length }}
      </div>
    </div>

    <div class="flex flex-1 flex-col gap-3">
      <ProjectBoardCard
        v-for="card in cards"
        :key="card.project_id"
        :card="card"
        @edit="emit('edit', $event)"
        @dragstart="emit('dragstart', $event)"
      />

      <div
        v-if="cards.length === 0"
        class="flex flex-1 items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-white/70 px-4 py-8 text-center text-sm text-slate-400"
      >
        Пусто
      </div>
    </div>
  </section>
</template>
