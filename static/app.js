(() => {
  const toast = document.querySelector('#toast');
  let toastTimer;

  window.ui = {
    csrf: document.body.dataset.csrf,
    showToast(message, isError = false) {
      if (!toast) return;
      toast.textContent = message;
      toast.classList.toggle('error', isError);
      toast.classList.add('visible');
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => toast.classList.remove('visible'), 3200);
    },
    async api(url, options = {}) {
      const response = await fetch(url, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': document.body.dataset.csrf,
          ...(options.headers || {})
        }
      });
      const data = await response.json().catch(() => ({ error: '服务器返回了无法解析的响应' }));
      if (!response.ok) throw new Error(data.error || `请求失败 (${response.status})`);
      return data;
    },
    async copy(value) {
      try {
        await navigator.clipboard.writeText(value);
      } catch (_error) {
        const helper = document.createElement('textarea');
        helper.value = value;
        helper.style.position = 'fixed';
        helper.style.opacity = '0';
        document.body.appendChild(helper);
        helper.select();
        document.execCommand('copy');
        helper.remove();
      }
      this.showToast('已复制到剪贴板');
    }
  };

  document.querySelectorAll('[data-open-dialog]').forEach(button => {
    button.addEventListener('click', () => document.getElementById(button.dataset.openDialog)?.showModal());
  });
  document.querySelectorAll('[data-close-dialog]').forEach(button => {
    button.addEventListener('click', () => button.closest('dialog')?.close());
  });
  document.querySelectorAll('[data-copy-target]').forEach(button => {
    button.addEventListener('click', () => {
      const input = document.getElementById(button.dataset.copyTarget);
      if (input?.value) window.ui.copy(input.value);
    });
  });
})();
