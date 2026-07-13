(() => {
  const dialog = document.querySelector('#command-dialog');
  const form = document.querySelector('#command-form');
  if (!dialog || !form) return;
  const error = form.querySelector('.form-error');
  const deleteButton = document.querySelector('#delete-command');
  const title = document.querySelector('#command-dialog-title');

  function resetForm() {
    form.reset();
    form.elements.id.value = '';
    error.textContent = '';
    title.textContent = '添加指令';
    deleteButton.classList.add('hidden');
  }
  document.querySelectorAll('[data-open-dialog="command-dialog"]').forEach(button => button.addEventListener('click', resetForm, { capture: true }));
  document.querySelectorAll('.edit-command').forEach(button => {
    button.addEventListener('click', () => {
      resetForm();
      form.elements.id.value = button.dataset.id;
      form.elements.name.value = button.dataset.name;
      form.elements.command.value = button.dataset.command;
      form.elements.host_id.value = button.dataset.hostId;
      title.textContent = `编辑 ${button.dataset.name}`;
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
      await window.ui.api(id ? `/api/commands/${id}` : '/api/commands', { method: id ? 'PUT' : 'POST', body: JSON.stringify(values) });
      window.location.reload();
    } catch (exception) { error.textContent = exception.message; }
  });
  deleteButton.addEventListener('click', async () => {
    const id = form.elements.id.value;
    if (!id || !window.confirm(`删除预设指令“${form.elements.name.value}”？`)) return;
    try {
      await window.ui.api(`/api/commands/${id}`, { method: 'DELETE' });
      window.location.reload();
    } catch (exception) { error.textContent = exception.message; }
  });
})();
