# Factories

## Definition with states

```php
// database/factories/PostFactory.php
class PostFactory extends Factory
{
    public function definition(): array
    {
        return [
            'user_id' => User::factory(),
            'title' => fake()->sentence(),
            'body' => fake()->paragraphs(3, true),
            'published_at' => null,
        ];
    }

    public function published(): static
    {
        return $this->state(fn () => ['published_at' => now()->subDay()]);
    }

    public function configure(): static
    {
        return $this->afterCreating(function (Post $post) {
            // e.g. attach default tags
        });
    }
}
```

## Relationships

| Need | Code |
| --- | --- |
| belongsTo | `Post::factory()->for($user)->create()` or `->for(User::factory()->admin())` |
| hasMany | `User::factory()->has(Post::factory()->count(3))->create()` / `->hasPosts(3)` |
| belongsToMany with pivot | `Post::factory()->hasAttached(Tag::factory()->count(2), ['weight' => 1])->create()` |
| polymorphic | `Comment::factory()->for($post, 'commentable')->create()` |
| sequence | `User::factory()->count(4)->sequence(['role' => 'admin'], ['role' => 'member'])->create()` |
| recycle shared parent | `Order::factory()->count(10)->recycle($store)->create()` |
| not persisted | `Post::factory()->make()` / `->raw()` for request payloads |

## Tips

- `create()` writes to the database, `make()` does not. Use `make()` in unit tests.
- Keep `definition()` minimal and valid; use states for variations (`unpaid()`, `admin()`).
- Unique values: `fake()->unique()->safeEmail()`.
- Payloads for POST tests: `Post::factory()->raw(['title' => ''])`.
- Avoid relying on seeders in tests; seed what each test needs, or use `$this->seed(RoleSeeder::class)`.
- Models need `use HasFactory;` (Laravel 8+). Laravel 11+ resolves factories by convention.
