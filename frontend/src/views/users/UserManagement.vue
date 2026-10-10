<template>
  <div class="page-container">
    <div class="page-header">
      <h1 class="page-title">用户管理</h1>
      <el-button v-if="activeTab === 'users'" type="primary" @click="openCreateDialog">
        <el-icon><Plus /></el-icon>
        新建用户
      </el-button>
      <el-button v-else type="primary" @click="openRoleDialog(null)">
        <el-icon><Plus /></el-icon>
        新建角色
      </el-button>
    </div>

    <el-tabs v-model="activeTab" class="mgmt-tabs">
      <!-- ==================== Tab1：用户 ==================== -->
      <el-tab-pane label="用户" name="users">
    <div class="card-container">
      <!-- 搜索栏 -->
      <div class="filter-bar">
        <el-input
          v-model="searchText"
          placeholder="搜索用户名或邮箱"
          clearable
          style="width: 280px"
          @input="handleSearch"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </div>

      <el-table :data="users" v-loading="loading" style="width: 100%">
        <el-table-column prop="username" label="用户名" width="140" />
        <el-table-column prop="email" label="邮箱" min-width="200" />
        <el-table-column prop="department" label="部门" width="120" />
        <el-table-column prop="position" label="职位" width="120" />
        <el-table-column prop="is_active" label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
              {{ row.is_active ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <!-- 所属角色：只读展示。成员在「角色」Tab 里维护，这里不支持修改 -->
        <el-table-column label="所属角色" min-width="180">
          <template #default="{ row }">
            <el-tag
              v-for="r in (row.roles || [])"
              :key="r.id"
              size="small"
              type="warning"
              style="margin: 2px 4px 2px 0"
            >
              {{ r.name }}
            </el-tag>
            <span v-if="!(row.roles || []).length" class="empty-text">未加入角色</span>
          </template>
        </el-table-column>
        <el-table-column prop="date_joined" label="注册时间" width="180">
          <template #default="{ row }">{{ formatDate(row.date_joined) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openEditDialog(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="deleteUser(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-container">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="fetchUsers"
        />
      </div>
    </div>

    <!-- 新建/编辑用户弹窗 -->
    <el-dialog
      v-model="showDialog"
      :title="isEdit ? '编辑用户' : '新建用户'"
      width="520px"
      destroy-on-close
      @close="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" :disabled="isEdit" placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="form.email" placeholder="请输入邮箱" />
        </el-form-item>
        <el-form-item v-if="!isEdit" label="密码" prop="password">
          <el-input v-model="form.password" type="password" placeholder="请输入密码" show-password />
        </el-form-item>
        <el-form-item v-if="!isEdit" label="确认密码" prop="password_confirm">
          <el-input v-model="form.password_confirm" type="password" placeholder="请确认密码" show-password />
        </el-form-item>
        <el-form-item label="姓名">
          <el-input v-model="form.first_name" placeholder="姓" style="width:48%;margin-right:4%" />
          <el-input v-model="form.last_name" placeholder="名" style="width:48%" />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="form.phone" placeholder="请输入手机号" />
        </el-form-item>
        <el-form-item label="部门">
          <el-input v-model="form.department" placeholder="请输入部门" />
        </el-form-item>
        <el-form-item label="职位">
          <el-input v-model="form.position" placeholder="请输入职位" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="form.is_active" active-text="启用" inactive-text="禁用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">
          {{ isEdit ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>
      </el-tab-pane>

      <!-- ==================== Tab2：角色 ==================== -->
      <el-tab-pane label="角色" name="roles">
        <div class="card-container">
          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="角色用于「按组授权」"
            description="在「项目管理」里编辑项目并选择归属角色，该角色下的成员会自动获得该项目的编辑权限（可查看、可编辑项目及项目下的用例/版本/模块等内容）。删除项目仍仅限项目负责人或管理员。角色本身只有管理员可以维护。"
            style="margin-bottom: 16px"
          />

          <el-table :data="roles" v-loading="rolesLoading" style="width: 100%">
            <el-table-column prop="name" label="角色名称" width="180" />
            <el-table-column prop="description" label="描述" min-width="180" show-overflow-tooltip />
            <el-table-column label="成员" min-width="260">
              <template #default="{ row }">
                <el-tag
                  v-for="m in (row.members || [])"
                  :key="m.id"
                  size="small"
                  style="margin: 2px 4px 2px 0"
                >
                  {{ m.username }}
                </el-tag>
                <span v-if="!(row.members || []).length" class="empty-text">暂无成员</span>
              </template>
            </el-table-column>
            <!-- 归属项目只读展示：角色的项目归属在「项目管理 → 编辑项目 → 归属角色」里设置，
                 不在这里双向维护，避免两个入口互相覆盖。 -->
            <el-table-column label="归属项目" min-width="240">
              <template #default="{ row }">
                <el-tag
                  v-for="p in (row.projects || [])"
                  :key="p.id"
                  size="small"
                  type="success"
                  style="margin: 2px 4px 2px 0"
                >
                  {{ p.name }}
                </el-tag>
                <span v-if="!(row.projects || []).length" class="empty-text">未归属项目</span>
                <div v-if="(row.projects || []).length" class="empty-text" style="margin-top:2px">
                  共 {{ row.project_count }} 个（在「项目管理」里调整）
                </div>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="160" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="openRoleDialog(row)">编辑</el-button>
                <el-button size="small" type="danger" @click="deleteRole(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!rolesLoading && !roles.length" description="还没有角色，点右上角「新建角色」开始" />
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 新建/编辑角色弹窗 -->
    <el-dialog
      v-model="showRoleDialog"
      :title="isRoleEdit ? '编辑角色' : '新建角色'"
      width="560px"
      destroy-on-close
    >
      <el-form :model="roleForm" label-width="80px">
        <el-form-item label="角色名称" required>
          <el-input v-model="roleForm.name" placeholder="如：测试组A / 支付业务组" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="roleForm.description" type="textarea" :rows="2" placeholder="可选" />
        </el-form-item>
        <el-form-item label="成员">
          <el-select
            v-model="roleForm.member_ids"
            multiple
            filterable
            placeholder="选择该角色下的用户"
            style="width: 100%"
          >
            <el-option
              v-for="u in allUsers"
              :key="u.id"
              :label="u.username + (u.email ? '（' + u.email + '）' : '')"
              :value="u.id"
            />
          </el-select>
          <div class="form-hint">
            这些用户会自动获得「归属该角色的项目」的编辑权限（不含删除项目）。<br />
            项目归属在<b>「项目管理 → 编辑项目 → 归属角色」</b>里设置。
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRoleDialog = false">取消</el-button>
        <el-button type="primary" :loading="roleSubmitting" @click="submitRole">
          {{ isRoleEdit ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Plus } from '@element-plus/icons-vue'
import api from '@/utils/api'
import dayjs from 'dayjs'

const activeTab = ref('users')
const loading = ref(false)
const submitting = ref(false)
const showDialog = ref(false)
const isEdit = ref(false)
const formRef = ref(null)

const users = ref([])
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)
const searchText = ref('')

const form = reactive({
  id: null,
  username: '',
  email: '',
  password: '',
  password_confirm: '',
  first_name: '',
  last_name: '',
  phone: '',
  department: '',
  position: '',
  is_active: true
})

const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 50, message: '3-50个字符', trigger: 'blur' }
  ],
  email: [
    { type: 'email', message: '请输入正确的邮箱格式', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少6位', trigger: 'blur' }
  ],
  password_confirm: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== form.password) {
          callback(new Error('两次密码不一致'))
        } else {
          callback()
        }
      },
      trigger: 'blur'
    }
  ]
}

// ==================== 角色管理 ====================
// 角色 = 组织级「组」：项目挂到角色下，角色成员自动获得该项目的编辑权限。
// 接口：/api/projects/roles/（后端仅管理员可增删改，所有人可读）
const ROLES_URL = '/projects/roles/'

const roles = ref([])
const rolesLoading = ref(false)
const showRoleDialog = ref(false)
const isRoleEdit = ref(false)
const roleSubmitting = ref(false)
const editingRoleId = ref(null)
const allUsers = ref([])
const roleForm = reactive({
  name: '',
  description: '',
  member_ids: []
})



const fetchRoles = async () => {
  rolesLoading.value = true
  try {
    const res = await api.get(ROLES_URL, { params: { page_size: 200 } })
    roles.value = res.data.results || res.data || []
  } catch (e) {
    ElMessage.error('获取角色列表失败：' + (e.response?.data?.detail || e.message))
  } finally {
    rolesLoading.value = false
  }
}

// 角色弹窗的成员下拉需要全部用户（不受用户列表分页/搜索影响）
const fetchAllUsers = async () => {
  try {
    const res = await api.get('/auth/users/', { params: { page_size: 500 } })
    allUsers.value = res.data.results || res.data || []
  } catch {
    allUsers.value = []
  }
}

// 角色弹窗只维护「成员」。项目归属统一在「项目管理 → 编辑项目 → 归属角色」里设置，
// 避免角色页和项目页两个入口双向改写同一个 Project.role 而互相覆盖。
const openRoleDialog = (row) => {
  isRoleEdit.value = !!row
  editingRoleId.value = row ? row.id : null
  roleForm.name = row ? row.name : ''
  roleForm.description = row ? (row.description || '') : ''
  roleForm.member_ids = row ? (row.members || []).map(m => m.id) : []
  showRoleDialog.value = true
}

const submitRole = async () => {
  if (!String(roleForm.name || '').trim()) {
    ElMessage.warning('请填写角色名称')
    return
  }
  roleSubmitting.value = true
  // ⚠️ 不传 project_ids：后端约定"传了才调整项目归属"，
  // 不传 = 完全不动项目的归属（避免覆盖在项目页做的设置）。
  const payload = {
    name: roleForm.name.trim(),
    description: roleForm.description || '',
    member_ids: roleForm.member_ids || []
  }
  try {
    if (isRoleEdit.value) {
      await api.patch(ROLES_URL + editingRoleId.value + '/', payload)
      ElMessage.success('角色已更新')
    } else {
      await api.post(ROLES_URL, payload)
      ElMessage.success('角色已创建')
    }
    showRoleDialog.value = false
    fetchRoles()
  } catch (e) {
    const d = e.response?.data || {}
    ElMessage.error(d.name?.[0] || d.detail || d.error || '保存失败')
  } finally {
    roleSubmitting.value = false
  }
}

const deleteRole = async (row) => {
  const n = row.project_count || 0
  const extra = n
    ? `\n\n⚠️ 该角色下还有 ${n} 个项目，删除后这些项目将失去角色授权（项目本身不会被删除，可重新挂到其他角色）。`
    : ''
  try {
    await ElMessageBox.confirm(
      `确定删除角色「${row.name}」吗？${extra}`,
      '删除角色',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await api.delete(ROLES_URL + row.id + '/')
    ElMessage.success('角色已删除')
    fetchRoles()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '删除失败（仅管理员可删除角色）')
  }
}

const fetchUsers = async () => {
  loading.value = true
  try {
    const params = { page: currentPage.value }
    if (searchText.value) params.search = searchText.value
    const res = await api.get('/auth/users/', { params })
    users.value = res.data.results || res.data || []
    total.value = res.data.count || 0
  } catch {
    ElMessage.error('获取用户列表失败')
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  currentPage.value = 1
  fetchUsers()
}

const openCreateDialog = () => {
  isEdit.value = false
  showDialog.value = true
}

const openEditDialog = (row) => {
  isEdit.value = true
  form.id = row.id
  form.username = row.username
  form.email = row.email || ''
  form.first_name = row.first_name || ''
  form.last_name = row.last_name || ''
  form.phone = row.phone || ''
  form.department = row.department || ''
  form.position = row.position || ''
  form.is_active = row.is_active
  form.password = ''
  form.password_confirm = ''
  showDialog.value = true
}

const resetForm = () => {
  Object.assign(form, {
    id: null, username: '', email: '', password: '', password_confirm: '',
    first_name: '', last_name: '', phone: '', department: '', position: '',
    is_active: true
  })
  formRef.value?.resetFields()
}

const handleSubmit = async () => {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    submitting.value = true
    try {
      if (isEdit.value) {
        // 编辑时不传密码
        const { password, password_confirm, ...payload } = form
        await api.put(`/auth/users/${form.id}/`, payload)
        ElMessage.success('用户更新成功')
      } else {
        await api.post('/auth/users/', form)
        ElMessage.success('用户创建成功')
      }
      showDialog.value = false
      resetForm()
      fetchUsers()
    } catch (e) {
      const msg = e.response?.data
      if (typeof msg === 'object') {
        // Django 字段校验错误
        const firstKey = Object.keys(msg)[0]
        ElMessage.error(msg[firstKey]?.[0] || '操作失败')
      } else {
        ElMessage.error(msg || '操作失败')
      }
    } finally {
      submitting.value = false
    }
  })
}

const deleteUser = async (row) => {
  try {
    await ElMessageBox.confirm(`确定要删除用户「${row.username}」吗？此操作不可撤销。`, '警告', {
      confirmButtonText: '确定删除',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await api.delete(`/auth/users/${row.id}/`)
    ElMessage.success('用户已删除')
    fetchUsers()
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

const formatDate = (d) => dayjs(d).format('YYYY-MM-DD HH:mm')

onMounted(() => {
  fetchUsers()
  // 角色列表、全量用户都预加载：切到「角色」Tab 时立即可用，
  // 不必等用户点击才请求（下拉选项要全量，不受列表分页/搜索影响）。
  fetchRoles()
  fetchAllUsers()
})
</script>

<style lang="scss" scoped>
.mgmt-tabs {
  margin-top: -6px;
}
.empty-text {
  color: #c0c4cc;
  font-size: 12px;
}
.form-hint {
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
  margin-top: 4px;
}
.warn-text {
  color: #e6a23c;
}
.filter-bar {
  margin-bottom: 16px;
}
.pagination-container {
  margin-top: 16px;
  display: flex;
  justify-content: center;
}
</style>
