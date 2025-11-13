async function loadCars() {
    const res = await fetch('/list');
    const cars = await res.json();
    const machines = {1: [], 2: [], 3: []};
    cars.forEach(c => machines[c[4]].push(c));
    for (let i=1;i<=3;i++) {
        const ul = document.querySelector('#m'+i+' ul');
        ul.innerHTML = '';
        machines[i].forEach(c => {
            const li = document.createElement('li');
            li.textContent = c[1];
            if (c[2]) li.classList.add('low');
            if (c[3]) li.classList.add('small');
            const btn = document.createElement('button');
            btn.textContent = '출차';
            btn.onclick = () => removeCar(c[0]);
            li.appendChild(btn);
            ul.appendChild(li);
        });
    }
}
async function addCar() {
    const plate =
document.getElementById('plate').value.trim();
    if (!plate) return alert('차량번호를 입력하세요');
    const small =
document.getElementById('small').checked;
    const machine =
document.getElementById('machine').value;
    const res = await fetch('/add', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({plate, small, machine})});
    if ((await res.json()).success) {
        document.getElementById('plate').value = '';
        loadCars();
    }
}
async function removeCar(id) {
    const res = await fetch('/remove', {method:'POST',
headers:{'Content-Type':'application/json'}, body:
JSON.stringify({id})});
    if ((await res.json()).success) loadCars();
}
loadCars();
setInterval(loadCars, 5000);
