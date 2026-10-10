/**
 * 元素拾取器 API（平台无关：Android / iOS，鸿蒙已预留）。
 *
 * 用途：把「设备上有什么元素」直接展示给用户，一键存进元素库。
 * 背景：之前 iOS 用例只能填一句自然语言描述，跑失败后才从日志里猜原因，
 *       每套用例都要反复试错。拾取器让用户**看得见、点得中**。
 *
 * ⚠️ 后端路由必须排在 router 之前（`elements/` 被 ElementViewSet 占着），
 *    否则 `elements/dump/` 会被当成 `elements/<pk=dump>/` 返回 405。
 */
import request from '../utils/api'

/** 抓取设备当前页面的元素（不落库，只返回列表） */
export function dumpDeviceElements(data) {
  return request({
    url: '/ui-automation/elements/dump/',
    method: 'post',
    data
  })
}

/** 把选中的元素存入元素库（按 project + platform + name 去重，重复则更新） */
export function savePickedElements(data) {
  return request({
    url: '/ui-automation/elements/save-picked/',
    method: 'post',
    data
  })
}

/** 定位失败时重新 dump 并自动修正 locator（可回写元素库） */
export function learnLocator(data) {
  return request({
    url: '/ui-automation/elements/learn-locator/',
    method: 'post',
    data
  })
}

/**
 * 用元素库校正用例步骤的「定位元素」（selector_hint）。
 *
 * 用途：自然语言生成的步骤只有 prompt，定位仍靠视觉模型猜；
 *      这个接口按描述去元素库找真元素（iOS=元素文案、Android=xpath）并回填。
 * 只返回结果不落库，由编辑器确认后保存 —— 匹配结论要能被人看见和修改。
 */
export function matchStepsToElements(data) {
  return request({
    url: '/ui-automation/elements/match-steps/',
    method: 'post',
    data,
    timeout: 60000
  })
}
