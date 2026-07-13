(() => {
  const dialog = document.querySelector('#host-dialog');
  const form = document.querySelector('#host-form');
  if (!dialog || !form) return;
  const error = form.querySelector('.form-error');
  const deleteButton = document.querySelector('#delete-host');
  const title = document.querySelector('#host-dialog-title');
  const passwordHint = document.querySelector('#password-hint');

  function resetForm() {
    form.reset();
    form.elements.id.value = '';
    form.elements.ssh_port.value = 22;
    form.elements.wol_broadcast.value = '255.255.255.255';
    form.elements.wol_port.value = 9;
    form.elements.password.required = true;
    error.textContent = '';
    title.textContent = '添加主机';
    passwordHint.textContent = '新增主机时必填';
    deleteButton.classList.add('hidden');
  }

  document.querySelectorAll('[data-open-dialog="host-dialog"]').forEach(button => {
    button.addEventListener('click', resetForm, { capture: true });
  });

  document.querySelectorAll('.edit-host').forEach(button => {
    button.addEventListener('click', () => {
      resetForm();
      for (const key of ['id', 'name', 'address', 'mac', 'username', 'ssh_port', 'wol_broadcast', 'wol_port']) {
        const datasetKey = key.replace(/_([a-z])/g, (_match, letter) => letter.toUpperCase());
        form.elements[key].value = button.dataset[datasetKey] || '';
      }
      form.elements.password.required = false;
      title.textContent = `编辑 ${button.dataset.name}`;
      passwordHint.textContent = '留空则保留现有密码';
      deleteButton.classList.remove('hidden');
      dialog.showModal();
    });
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    error.textContent = '';
    const values = Object.fromEntries(new FormData(form));
    const id = values.id;
    delete values.id;
    try {
      await window.ui.api(id ? `/api/hosts/${id}` : '/api/hosts', {
        method: id ? 'PUT' : 'POST', body: JSON.stringify(values)
      });
      window.location.reload();
    } catch (exception) {
      error.textContent = exception.message;
    }
  });

  deleteButton.addEventListener('click', async () => {
    const id = form.elements.id.value;
    const name = form.elements.name.value;
    if (!id || !window.confirm(`删除“${name}”？该主机的专属指令也会一并删除。`)) return;
    try {
      await window.ui.api(`/api/hosts/${id}`, { method: 'DELETE' });
      window.location.reload();
    } catch (exception) {
      error.textContent = exception.message;
    }
  });

  document.querySelectorAll('.wake-host').forEach(button => {
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        const result = await window.ui.api(`/api/hosts/${button.dataset.id}/wake`, { method: 'POST', body: '{}' });
        window.ui.showToast(result.message);
      } catch (exception) {
        window.ui.showToast(exception.message, true);
      } finally {
        button.disabled = false;
      }
    });
  });
})();
