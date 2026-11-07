export default function generate(THREE) {
  const oriented = new THREE.Group();
  oriented.add(__r3Build(THREE));
  oriented.rotation.y = __R3_YAW__;
  oriented.updateMatrixWorld(true);
  const dimensions = new THREE.Box3().setFromObject(oriented, true).getSize(new THREE.Vector3());
  if (dimensions.y < 0.5 * Math.max(dimensions.x, dimensions.z)) {
    oriented.rotation.x = __R3_PITCH__;
    oriented.updateMatrixWorld(true);
  }
  // Flatten drawable nodes without changing their world-space surfaces. Baking
  // ordinary geometry removes rotated local-box overestimation during the fit.
  // Instance transforms remain intact so repeated parts do not become draws.
  const root = new THREE.Group();
  oriented.traverse(function (item) {
    if (!(item.isMesh || item.isLine || item.isPoints) || !item.geometry) return;
    const copy = item.clone(false);
    let visible = true;
    for (let ancestor = item; ancestor; ancestor = ancestor.parent) {
      visible = visible && ancestor.visible;
    }
    copy.visible = visible;
    if (item.isInstancedMesh) {
      copy.matrixAutoUpdate = false;
      copy.matrix.copy(item.matrixWorld);
    } else {
      const origin = new THREE.Vector3().setFromMatrixPosition(item.matrixWorld);
      const transform = new THREE.Matrix4().makeTranslation(-origin.x, -origin.y, -origin.z);
      transform.multiply(item.matrixWorld);
      copy.geometry = item.geometry.clone().applyMatrix4(transform);
      if (item.isMesh && item.matrixWorld.determinant() < 0) {
        const geometry = copy.geometry;
        const count = geometry.index ? geometry.index.count : geometry.attributes.position.count;
        const order = new Uint32Array(Math.floor(count / 3) * 3);
        for (let i = 0; i < order.length; i += 3) {
          order[i] = geometry.index ? geometry.index.getX(i) : i;
          order[i + 1] = geometry.index ? geometry.index.getX(i + 2) : i + 2;
          order[i + 2] = geometry.index ? geometry.index.getX(i + 1) : i + 1;
        }
        geometry.setIndex(new THREE.BufferAttribute(order, 1));
        const tangent = geometry.attributes.tangent;
        if (tangent) {
          for (let i = 0; i < tangent.count; i++) tangent.setW(i, -tangent.getW(i));
        }
      }
      copy.position.copy(origin);
      copy.quaternion.identity();
      copy.scale.set(1, 1, 1);
      copy.matrixAutoUpdate = true;
    }
    root.add(copy);
  });
  root.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(root);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const extent = Math.max(size.x, size.y, size.z);
  if (!(extent > 0) || !Number.isFinite(extent)) throw new Error('Invalid asset bounds');
  const scale = 0.98 / extent;
  root.scale.setScalar(scale);
  root.position.set(-center.x * scale, -center.y * scale, -center.z * scale);
  root.updateMatrixWorld(true);
  return root;
}
