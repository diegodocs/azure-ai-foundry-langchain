<script setup>
import { ref, watch, nextTick } from 'vue'
import WelcomeScreen from './WelcomeScreen.vue'
import MessageRow from './MessageRow.vue'

const props = defineProps({
  messages: { type: Array, required: true },
})

const emit = defineEmits(['suggestion'])

const container = ref(null)

// Rola para o fundo a cada atualização de mensagens
watch(
  () => props.messages,
  () => {
    nextTick(() => {
      if (container.value) container.value.scrollTop = container.value.scrollHeight
    })
  },
  { deep: true },
)
</script>

<template>
  <div class="messages" ref="container">
    <WelcomeScreen v-if="!messages.length" @select="emit('suggestion', $event)" />
    <MessageRow v-for="msg in messages" :key="msg.id" :msg="msg" />
  </div>
</template>
