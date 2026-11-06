export default function generate(THREE) {
  const asset = __r3Build(THREE);
  const root = new THREE.Group();
  root.add(asset);
  root.rotation.y = __R3_YAW__;
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
