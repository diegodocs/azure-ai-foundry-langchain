<script setup>
const emit = defineEmits(['select'])

const suggestions = [
  '📦 Quais produtos têm na linha premium?',
  '🌐 Quais promoções têm no site?',
  '🎫 Quero abrir um chamado de suporte',
  '📋 Liste meus chamados abertos',
]
</script>

<template>
  <div class="welcome">
    <div class="icon">✨</div>
    <h2>Como posso ajudar?</h2>
    <p>Escolha um agente automaticamente com base na sua pergunta, ou experimente uma das sugestões abaixo.</p>
    <div class="suggestions">
      <button
        v-for="s in suggestions"
        :key="s"
        class="suggestion-btn"
        @click="emit('select', s)"
      >{{ s }}</button>
    </div>
  </div>
</template>
